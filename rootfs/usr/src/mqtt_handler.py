"""
MQTT Handler Module

Contains the TaskDoMQTT class for handling MQTT communication, data publishing, and state recovery.
"""

import threading
import time
import datetime
import json
import logging
import ssl
import urllib.request
import os
import copy
import re
import paho.mqtt.client as mqtt
import state as state_module
import discovery

logger = logging.getLogger(__name__)

class TaskDoMQTT(threading.Thread):

    def __init__(self, trigger, stopper):
        super().__init__()
        self._trigger = trigger
        self._stopper = stopper
        self._connected = False
        self._global_discovery_sent = False
        self._discovered_meters = {} # Track {meter_id: "name"}
        self._recovery_complete = False
        self._mqttc = None
        self._last_diagnostics = {}

    def _fetch_ha_state(self, entity_id):
        """Fetch the current state of an entity from Home Assistant REST API."""
        token = os.getenv('SUPERVISOR_TOKEN')
        if not token:
            return None

        url = f"http://supervisor/core/api/states/{entity_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    state = data.get('state')
                    if state not in [None, 'unknown', 'unavailable']:
                        return state
        except Exception as e:
            logger.debug(f"HA API state fetch for {entity_id} failed: {e}")
        return None

    def _fetch_all_ha_states(self):
        """Fetch all entity states from Home Assistant."""
        token = os.getenv('SUPERVISOR_TOKEN')
        if not token:
            return []

        url = "http://supervisor/core/api/states"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    return json.loads(response.read().decode())
        except Exception as e:
            logger.debug(f"HA API fetch all states failed: {e}")
        return []

    def _recover_state(self):
        """Startup phase: Wait for retained messages or HA API to recover meter totals."""
        # No globals needed, using state_module directly
        
        # We always perform recovery now as we are stateless
        logger.info("Starting State Recovery phase...")
        
        # 1. Subscribe to state topics to get retained messages
        # We need a temporary client or use the main one? Main one is connected.
        # But main loop hasn't started.
        
        # Subscribe to all potential meters: base_topic/+/total, base_topic/+/name
        # And let on_message handle updates to 'measurement'
        
        # However, paho mqtt loop needs to run.
        # Ideally we wait a bit for retained messages to arrive.
        
        recovered_data = {} # {identifier: {'total': X}}
        recovered_names = {} # {name: id}
        
        base_topic = state_module.config['mqtt']['base_topic']
        discovery_prefix = state_module.config['mqtt']['discovery_prefix']

        def on_recovery_message(client, userdata, msg):
            try:
                # 1. Handle Discovery topics to rebuild name-to-id mapping
                if '/config' in msg.topic:
                    payload = json.loads(msg.payload.decode())
                    unique_id = payload.get('unique_id', '')
                    state_topic = payload.get('state_topic', '')
                    
                    match_id = re.search(fr"s0pcm_{base_topic}_(\d+)", unique_id)
                    if match_id:
                        meter_id = int(match_id.group(1))
                        name_part = state_topic.replace(f"{base_topic}/", "")
                        name = name_part.split('/')[0]
                        if name and name != str(meter_id) and recovered_names.get(name) != meter_id:
                            recovered_names[name] = meter_id
                            logger.info(f"Recovery: Mapped Name '{name}' to ID {meter_id}")
                    return

                # 2. Handle Data topics
                topic_parts = msg.topic.split('/')
                if len(topic_parts) >= 3:
                    suffix = topic_parts[-1]
                    if suffix in ['total', 'today', 'yesterday', 'pulsecount']:
                        identifier = topic_parts[-2]
                        payload = msg.payload.decode()
                        try:
                            value = int(float(payload))
                            recovered_data.setdefault(identifier, {})[suffix] = value
                        except ValueError:
                            pass
                
                if msg.topic.endswith('/date'):
                    try:
                        dt = datetime.date.fromisoformat(msg.payload.decode())
                        with state_module.lock:
                            state_module.measurement['date'] = dt
                    except ValueError:
                        pass
            except Exception as e:
                logger.debug(f"Recovery parse error: {e}")

        # Hijack callbacks for recovery
        original_on_message = self._mqttc.on_message
        self._mqttc.on_message = on_recovery_message
        
        # Subscribe to all potential topics
        topics = [
            f"{base_topic}/+/total",
            f"{base_topic}/+/name",
            f"{base_topic}/+/pulsecount",
            f"{base_topic}/+/today",
            f"{base_topic}/+/yesterday",
            f"{base_topic}/date",
            f"{discovery_prefix}/sensor/{base_topic}/#"
        ]
        
        for t in topics:
            self._mqttc.subscribe(t)
            
        logger.info("Recovery: Waiting 7s for MQTT retained messages...")
        time.sleep(7)
        
        # Restore callback
        self._mqttc.on_message = original_on_message
        for t in topics:
            self._mqttc.unsubscribe(t)
            
        # Process recovered data
        if recovered_data:
            with state_module.lock:
                for identifier, data in recovered_data.items():
                    meter_id = None
                    try:
                        meter_id = int(identifier)
                    except ValueError:
                        meter_id = recovered_names.get(identifier)
                    
                    if meter_id:
                        state_module.measurement.setdefault(meter_id, {})
                        for field, val in data.items():
                            if field not in state_module.measurement[meter_id] or val > state_module.measurement[meter_id].get(field, 0):
                                state_module.measurement[meter_id][field] = val
                                logger.info(f"Recovered {field} for meter {meter_id}: {val}")
                        
                        # Apply name mapping
                        for name, mid in recovered_names.items():
                            if mid == meter_id:
                                state_module.measurement[meter_id]['name'] = name
                                break

            
        # Re-subscribe to operational topics (set commands) done in on_connect
        # But we need to ensure we subscribe effectively. on_connect handles it.
        
        # 2. Recover from Split Topics (s0/Kitchen/total) if necessary
        # If we have meters with Name but NO total (because total was published to s0/Name/total),
        # we try to fetch that if we know the name.
        if state_module.config['mqtt']['split_topic']:
            logger.info("Recovery: Checking split topics for named meters...")
            # We can't easily iterate retained messages again. 
            # We rely on HA API fallback for this mostly, or if s0/ID/total was also retained.
            # (Note: _publish_measurements publishes s0/ID/total ALWAYS for recovery).
            pass

        # Check what we have
        with state_module.lock:
            for meter_id, data in state_module.measurement.items():
                if isinstance(meter_id, int):
                    if 'total' in data:
                        logger.info(f"Recovery: Meter {meter_id} recovered via MQTT (Total: {data['total']})")
                    else:
                        logger.info(f"Recovery: Meter {meter_id} found via MQTT but 'total' missing.")

        # 3. Fallback to HA API for missing meters
        # We check meters 1 to 5 (standard S0PCM-5)
        all_states = None
        for meter_id in range(1, 6):
            if meter_id not in state_module.measurement or 'total' not in state_module.measurement[meter_id]:
                logger.info(f"Recovery: Meter {meter_id} not found on MQTT, attempting HA API fallback...")
                
                # Phase A: Try specific patterns (fast)
                entity_patterns = [
                    f"sensor.{state_module.config['mqtt']['base_topic']}_{meter_id}_total",
                    f"sensor.s0pcm_reader_{meter_id}_total",
                    f"sensor.{meter_id}_total"
                ]
                
                ha_total = None
                for ha_entity in entity_patterns:
                    ha_total = self._fetch_ha_state(ha_entity)
                    if ha_total:
                        break
                
                # Phase B: Fuzzy search across ALL entities if Phase A failed
                if not ha_total:
                    if all_states is None:
                        logger.debug("Recovery: Fetching all HA states for fuzzy matching...")
                        all_states = self._fetch_all_ha_states()
                    
                    # Search patterns for this meter_id
                    keywords = ['total', 'totaal', 'today', 'vandaag', 'dag']
                    exclude_keywords = ['cost', 'prijs', 'price', 'integral', 'energy', 'gas', 'power', 'spanning', 'stroom', 'consumption', 'delivery', 'koffie', 'coffee']
                    
                    for item in all_states:
                        entity_id = item.get('entity_id', '').lower()
                        state_str = str(item.get('state', '')).lower()
                        
                        # Check if this entity is a plausible candidate for this meter_id
                        is_match = False
                        
                        # Domain Lock: Only consider if it belongs to S0PCM Reader specifically
                        is_our_domain = (state_module.config['mqtt']['base_topic'] in entity_id) or entity_id.startswith("sensor.s0pcm_")
                        
                        # 1. ID based match: sensor.s0pcm_1_total, sensor.meter_1, etc.
                        if is_our_domain:
                            if f"_{meter_id}_" in entity_id or entity_id.endswith(f"_{meter_id}"):
                                if any(k in entity_id for k in keywords):
                                    is_match = True
                        
                        # 2. Specific fallback for Meter 1 (Water) if it was renamed to something generic like "Watermeter Totaal"
                        if not is_match and meter_id == 1:
                            if "watermeter_totaal" in entity_id or "watermeter_total" in entity_id:
                                is_match = True

                        if is_match:
                            # Strict Exclusions: Never pick up costs, integrals, or energy prices
                            if any(x in entity_id for x in exclude_keywords):
                                logger.debug(f"Recovery: Skipping {entity_id} for Meter {meter_id} (Matched exclusion keyword)")
                                continue

                            if state_str in [None, 'unknown', 'unavailable', '']:
                                logger.debug(f"Recovery: Skipping {entity_id} for Meter {meter_id} (State is '{state_str}')")
                                continue

                            # Clean the state string (remove units, handle European thousand separators)
                            # e.g. "1.323.394 m3" -> "1323394"
                            clean_state = state_str
                            for unit in ['m³', 'm3', 'kwh', 'l/min', 'l']:
                                if unit in clean_state:
                                    clean_state = clean_state.replace(unit, '')
                            
                            # Remove non-numeric chars except . , and -
                            clean_state = "".join(c for c in clean_state if c.isdigit() or c in '.,-')
                            
                            # If it has multiple dots/commas, it's likely thousand separators
                            if clean_state.count('.') > 1 or clean_state.count(',') > 1 or (clean_state.count('.') == 1 and clean_state.count(',') == 1):
                                clean_state = clean_state.replace('.', '').replace(',', '')
                            elif clean_state.count(',') == 1 and '.' not in clean_state:
                                # Likely decimal comma (European), treat as dot for float()
                                clean_state = clean_state.replace(',', '.')
                            
                            clean_state = clean_state.strip()
                            
                            try:
                                if not clean_state: continue
                                val = float(clean_state)
                                ha_total = str(val)
                                logger.info(f"Recovery: Found surgical match for Meter {meter_id}: {entity_id} = {ha_total} (was '{state_str}')")
                                break
                            except ValueError:
                                logger.debug(f"Recovery: Skipping {entity_id} - could not parse '{clean_state}' as number")
                                continue

                if ha_total:
                    try:
                        total_val = int(float(ha_total))
                        with state_module.lock:
                            state_module.measurement.setdefault(meter_id, {})['total'] = total_val
                            state_module.measurement[meter_id].setdefault('today', 0)
                            state_module.measurement[meter_id].setdefault('yesterday', 0)
                            state_module.measurement[meter_id].setdefault('pulsecount', 0)
                        logger.info(f"Recovery: Recovered total for meter {meter_id} from HA API: {total_val}")
                    except ValueError:
                        pass
        
        # Finalize
        with state_module.lock:
            state_module.measurementshare = copy.deepcopy(state_module.measurement)
        
        self._recovery_complete = True
        state_module.recovery_event.set() # Signal Serial Task to start
        logger.info("State Recovery complete.")

    def on_connect(self, mqttc, obj, flags, reason_code, properties):
        if reason_code == 0:
            self._connected = True
            self._discovery_sent = False
            logger.debug('MQTT successfully connected to broker')
            self._trigger.set()
            self._mqttc.publish(state_module.config['mqtt']['base_topic'] + '/status', state_module.config['mqtt']['online'], retain=state_module.config['mqtt']['retain'])
            
            # Subscribe to 'set' commands
            self._mqttc.subscribe(state_module.config['mqtt']['base_topic'] + '/+/total/set')
            self._mqttc.subscribe(state_module.config['mqtt']['base_topic'] + '/+/name/set')
            logger.debug(f"Subscribed to set commands under {state_module.config['mqtt']['base_topic']}/+/...")
        else:
            self._connected = False
            state_module.SetError(f"MQTT failed to connect to broker: {mqtt.connack_string(reason_code)}", category='mqtt')

    def on_disconnect(self, mqttc, obj, flags, reason_code, properties):
        self._connected = False
        if reason_code == 0:
            logger.debug('MQTT successfully disconnected from broker')
        else:
            state_module.SetError(f"MQTT failed to disconnect from broker: {mqtt.connack_string(reason_code)}", category='mqtt')
            logger.error(f"MQTT disconnected unexpectedly. Reason: {reason_code} ({mqtt.connack_string(reason_code)})")

    def on_message(self, mqttc, obj, msg):
        logger.debug('MQTT on_message: ' + msg.topic + ' ' + str(msg.qos) + ' ' + str(msg.payload))

        # Check for set commands
        if msg.topic.endswith('/total/set'):
            self._handle_set_command(msg)
        elif msg.topic.endswith('/name/set'):
            self._handle_name_set(msg)

    def _handle_set_command(self, msg):
        # No global measurementshare needed
        try:
            # Topic format: base_topic/ID_or_NAME/total/set
            parts = msg.topic.split('/')
            identifier = parts[-3]
            meter_id = None
            
            try:
                meter_id = int(identifier)
            except ValueError:
                # If not an integer, try to find a meter with a matching name (case-insensitive)
                for key, data in state_module.measurement.items():
                    if isinstance(key, int):
                        name = data.get('name')
                        if name and name.lower() == identifier.lower():
                            meter_id = key
                            break
            
            if meter_id is None:
                state_module.SetError(f"Ignored set command for unknown meter ID or Name: {identifier}", category='mqtt')
                return

            payload_str = msg.payload.decode('utf-8')
            try:
                # Support int or float input, but store as likely int
                new_total = int(float(payload_str))
            except ValueError:
                state_module.SetError(f"Ignored invalid payload for set command on meter {meter_id}: {payload_str}", category='mqtt')
                return

            logger.info(f"Received MQTT set command for meter {meter_id}. Setting total to {new_total}.")

            with state_module.lock:
                if meter_id not in state_module.measurement:
                    state_module.measurement[meter_id] = {}
                    state_module.measurement[meter_id].setdefault('pulsecount', 0)
                    state_module.measurement[meter_id].setdefault('today', 0)
                    state_module.measurement[meter_id].setdefault('yesterday', 0)

                state_module.measurement[meter_id]['total'] = new_total
                
                # Persist immediately
                state_module.SaveMeasurement()
                logger.debug(f"Updated measurement file with new total for meter {meter_id}")

                # Update share and trigger publish
                state_module.measurementshare = copy.deepcopy(state_module.measurement)
                self._trigger.set()

        except Exception as e:
            state_module.SetError(f"Failed to process MQTT set command: {e}", category='mqtt')

    def _handle_name_set(self, msg):
        """Handle MQTT command to set or clear a meter name."""
        try:
            # Topic format: base_topic/ID_or_NAME/name/set
            parts = msg.topic.split('/')
            identifier = parts[-3]
            meter_id = None
            
            try:
                meter_id = int(identifier)
            except ValueError:
                # If not an integer, try to find a meter with a matching name (case-insensitive)
                for key, data in state_module.measurement.items():
                    if isinstance(key, int):
                        name = data.get('name')
                        if name and name.lower() == identifier.lower():
                            meter_id = key
                            break
            
            if meter_id is None:
                state_module.SetError(f"Ignored name/set command for unknown meter ID or Name: {identifier}", category='mqtt')
                return

            new_name = msg.payload.decode('utf-8').strip()
            
            # If payload is empty, clear the name
            if not new_name:
                new_name = None

            logger.info(f"Received MQTT name/set command for meter {meter_id}. Setting name to: {new_name or 'None (ID only)'}")

            with state_module.lock:
                if meter_id not in state_module.measurement:
                    state_module.measurement[meter_id] = {}
                    state_module.measurement[meter_id].setdefault('pulsecount', 0)
                    state_module.measurement[meter_id].setdefault('total', 0)
                    state_module.measurement[meter_id].setdefault('today', 0)
                    state_module.measurement[meter_id].setdefault('yesterday', 0)

                if new_name:
                    state_module.measurement[meter_id]['name'] = new_name
                else:
                    if 'name' in state_module.measurement[meter_id]:
                        del state_module.measurement[meter_id]['name']
                
                # Persist immediately
                state_module.SaveMeasurement()
                
                # Update share and trigger discovery to update HA entities
                state_module.measurementshare = copy.deepcopy(state_module.measurement)
                discovery.send_global_discovery(self._mqttc)
                for mid in state_module.measurementshare:
                    if isinstance(mid, int):
                        instancename = discovery.send_meter_discovery(self._mqttc, mid, state_module.measurementshare[mid])
                        if instancename:
                            self._discovered_meters[mid] = instancename
                self._global_discovery_sent = True
                self._trigger.set()

        except Exception as e:
            state_module.SetError(f"Failed to process MQTT name/set command: {e}", category='mqtt')

    def on_publish(self, mqttc, obj, mid, reason_codes, properties):
        logger.debug('MQTT on_publish: mid: ' + str(mid))

    def on_subscribe(self, mqttc, obj, mid, reason_codes, properties):
        logger.debug('MQTT on_subscribe: ' + str(mid) + ' ' + str(reason_codes))

    def on_log(self, mqttc, obj, level, string):
        logger.debug('MQTT on_log: ' + string)

    # Discovery methods moved to discovery.py


    def _setup_mqtt_client(self, use_tls):
        # Define our MQTT Client
        self._mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=state_module.config['mqtt']['client_id'], protocol=state_module.config['mqtt']['version'])
        self._mqttc.on_connect = self.on_connect
        self._mqttc.on_disconnect = self.on_disconnect
        self._mqttc.on_message = self.on_message
        #self._mqttc.on_publish = self.on_publish
        #self._mqttc.on_subscribe = self.on_subscribe

        # https://github.com/eclipse/paho.mqtt.python/blob/master/examples/client_pub-wait.py

        if state_module.config['mqtt']['username'] != None:
            self._mqttc.username_pw_set(state_module.config['mqtt']['username'], state_module.config['mqtt']['password'])

        # Setup TLS if requested
        if use_tls:
            try:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            except AttributeError:
                # Fallback for older Python versions
                context = ssl.SSLContext(ssl.PROTOCOL_TLS)

            if state_module.config['mqtt']['tls_ca'] == '':
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            else:
                if state_module.config['mqtt']['tls_check_peer']:
                    context.verify_mode = ssl.CERT_REQUIRED
                    context.check_hostname = True
                else:
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                
                try:
                    context.load_verify_locations(cafile=state_module.config['mqtt']['tls_ca'])
                except Exception as e:
                    state_module.SetError(f"Failed to load TLS CA file '{state_module.config['mqtt']['tls_ca']}': {str(e)}", category='mqtt')
                    return False

            self._mqttc.tls_set_context(context=context)

        # Set last will
        self._mqttc.will_set(state_module.config['mqtt']['base_topic'] + '/status', state_module.config['mqtt']['lastwill'], retain=state_module.config['mqtt']['retain'])
        return True

    def _connect_loop(self):
        """Retry loop to establish connection."""
        use_tls = state_module.config['mqtt']['tls']
        fallback_happened = False

        while not self._stopper.is_set():
            if not self._mqttc and not self._setup_mqtt_client(use_tls):
                 time.sleep(state_module.config['mqtt']['connect_retry'])
                 continue

            plain_port = int(state_module.config['mqtt']['port'])
            tls_port = int(state_module.config['mqtt']['tls_port'])
            current_port = tls_port if use_tls else plain_port

            logger.debug(f"Connecting to MQTT Broker '{state_module.config['mqtt']['host']}:{current_port}' (TLS: {use_tls})")
            
            try:
                self._mqttc.connect(state_module.config['mqtt']['host'], current_port, 60)
                self._mqttc.loop_start()
                
                # Wait for connection to be established via on_connect callback
                timeout = time.time() + 10 
                while time.time() < timeout and not self._connected and not self._stopper.is_set():
                    time.sleep(0.5)

                if self._connected:
                    logger.debug("MQTT connection established")
                    self._recover_state() # Perform state recovery
                    return # Connected
                else:
                    raise ConnectionError("Timeout waiting for MQTT CONNACK")

            except (ssl.SSLError, ssl.CertificateError, ConnectionResetError, ConnectionError, OSError) as e:
                if self._mqttc:
                    self._mqttc.loop_stop()
                    self._mqttc = None # force reset

                if use_tls and not fallback_happened:
                    state_module.SetError(f"MQTT TLS connection failed: {type(e).__name__}: '{str(e)}'. Falling back to plain MQTT.", category='mqtt')
                    use_tls = False
                    fallback_happened = True
                else:
                    state_module.SetError(f"MQTT connection failed: {type(e).__name__}: '{str(e)}'", category='mqtt')
                    time.sleep(state_module.config['mqtt']['connect_retry'])
            except Exception as e:
                if self._mqttc:
                    self._mqttc.loop_stop()
                    self._mqttc = None
                state_module.SetError(f"MQTT connection failed unexpectedly: {type(e).__name__}: '{str(e)}'", category='mqtt')
                time.sleep(state_module.config['mqtt']['connect_retry'])

    def _publish_diagnostics(self):
        """Publish dynamic diagnostics info."""
        try:
            current_diagnostics = {
                'version': state_module.s0pcmreaderversion,
                'firmware': state_module.s0pcm_firmware,
                'startup_time': state_module.startup_time,
                'port': state_module.config['serial']['port']
            }

            for key, val in current_diagnostics.items():
                if key not in self._last_diagnostics or self._last_diagnostics[key] != val:
                    topic = state_module.config['mqtt']['base_topic'] + '/' + key
                    self._mqttc.publish(topic, str(val), retain=state_module.config['mqtt']['retain'])
                    self._last_diagnostics[key] = val
            
            # Legacy JSON info
            info_payload = {
                "version": state_module.s0pcmreaderversion,
                "s0pcm_firmware": state_module.s0pcm_firmware,
                "startup_time": state_module.startup_time,
                "serial_port": state_module.config['serial']['port']
            }
            self._mqttc.publish(state_module.config['mqtt']['base_topic'] + '/info', json.dumps(info_payload), retain=state_module.config['mqtt']['retain'])
        except Exception as e:
            logger.error(f"Failed to publish info state to MQTT: {e}")

    def _publish_measurements(self, measurementlocal, measurementprevious):
        """Publish meter values."""
        # Persistent Global Date
        current_date = str(measurementlocal.get('date', ""))
        previous_date = str(measurementprevious.get('date', ""))
        if current_date != previous_date:
            self._mqttc.publish(state_module.config['mqtt']['base_topic'] + '/date', current_date, retain=True)

        for key in measurementlocal:
            if isinstance(key, int):

                if not measurementlocal[key].get('enabled', True):
                        continue

                jsondata = {}
                instancename = measurementlocal[key].get('name', str(key))

                # Internal persistent topics
                for internal_field in ['pulsecount', 'total', 'today', 'yesterday']:
                    if internal_field in measurementlocal[key]:
                        # Always publish ID-based internal topics for recovery, 
                        # but only on change to reduce traffic
                        val = measurementlocal[key][internal_field]
                        old_val = measurementprevious.get(key, {}).get(internal_field)
                        if val != old_val:
                            self._mqttc.publish(f"{state_module.config['mqtt']['base_topic']}/{key}/{internal_field}", val, retain=True)

                for subkey in ['total', 'today', 'yesterday']:
                    value_previous = measurementprevious.get(key, {}).get(subkey, -1)
                    
                    try:
                        if subkey in measurementlocal[key]:
                            if state_module.config['mqtt']['split_topic'] == True:
                                # On-change check (value and name/topic)
                                if measurementlocal[key][subkey] == value_previous and \
                                   measurementlocal[key].get('name') == measurementprevious.get(key, {}).get('name'):
                                    continue
                                
                                
                                logger.debug(f"MQTT Publish: topic='{state_module.config['mqtt']['base_topic']}/{instancename}/{subkey}', value='{measurementlocal[key][subkey]}'")
                                self._mqttc.publish(state_module.config['mqtt']['base_topic'] + '/' + instancename + '/' + subkey, measurementlocal[key][subkey], retain=state_module.config['mqtt']['retain'])
                            else:
                                jsondata[subkey] = measurementlocal[key][subkey]

                    except Exception as e:
                        state_module.SetError(f"MQTT Publish Failed for {instancename}/{subkey}. {type(e).__name__}: '{str(e)}'", category='mqtt')

                # Publish Name State (for text entity) if name changed
                current_name = measurementlocal[key].get('name', "")
                previous_name = measurementprevious.get(key, {}).get('name', "")
                if current_name != previous_name or not measurementprevious:
                    try:
                        name_topic = f"{state_module.config['mqtt']['base_topic']}/{key}/name"
                        logger.debug(f"MQTT Publish Name: topic='{name_topic}', value='{current_name}'")
                        self._mqttc.publish(name_topic, current_name, retain=True)
                    except Exception as e:
                        state_module.SetError(f"MQTT Publish Name Failed for {key}. {type(e).__name__}: '{str(e)}'", category='mqtt')

                # Publish JSON if not split
                if state_module.config['mqtt']['split_topic'] == False and jsondata:
                    try:
                        logger.debug(f"MQTT Publish JSON: topic='{state_module.config['mqtt']['base_topic']}/{instancename}', value='{json.dumps(jsondata)}'")
                        self._mqttc.publish(state_module.config['mqtt']['base_topic'] + '/' + instancename, json.dumps(jsondata), retain=state_module.config['mqtt']['retain'])
                    except Exception as e:
                        state_module.SetError(f"MQTT Publish Failed for {instancename} (JSON). {type(e).__name__}: '{str(e)}'", category='mqtt')

    def _main_loop(self):
        """Main processing loop when connected."""
        measurementprevious = {}
        # Initial sync - removed pre-population to force first publish of all values
        # This ensures that any name/topic changes are immediately visible on startup.

        while not self._stopper.is_set():
            # Snapshot data
            with state_module.lock:
                measurementlocal = copy.deepcopy(state_module.measurementshare)
                errorlocal = state_module.lasterrorshare

            # Connection check - if lost, return to connect loop to trigger re-connection logic
            if not self._connected:
                logger.warning('MQTT Connection lost, returning to connect loop...')
                return 

            if not self._global_discovery_sent:
                discovery.send_global_discovery(self._mqttc)
                self._global_discovery_sent = True

            # Dynamic Meter Discovery
            for mid in measurementlocal:
                if isinstance(mid, int):
                    current_name = measurementlocal[mid].get('name', str(mid))
                    if mid not in self._discovered_meters or self._discovered_meters[mid] != current_name:
                        instancename = discovery.send_meter_discovery(self._mqttc, mid, measurementlocal[mid])
                        if instancename:
                            self._discovered_meters[mid] = instancename

            self._publish_diagnostics()
            self._publish_measurements(measurementlocal, measurementprevious)

            # Publish Error
            error_published = False
            try:
                error_payload = errorlocal if errorlocal else "No Error"
                self._mqttc.publish(state_module.config['mqtt']['base_topic'] + '/error', error_payload, retain=state_module.config['mqtt']['retain'])
                error_published = True
            except Exception as e:
                state_module.SetError(f"MQTT Publish Failed for error topic. {type(e).__name__}: '{str(e)}'", category='mqtt')

            if self._connected and error_published:
                state_module.SetError(None, category='mqtt', trigger_event=False)

            measurementprevious = copy.deepcopy(measurementlocal)

            # Wait for next event
            self._trigger.wait()
            self._trigger.clear()

    def run(self):
        try:
            while not self._stopper.is_set():
                # Establish connection
                self._connect_loop()
                # Run main logic
                self._main_loop()
                # If _main_loop returns, it means we stopped or need full reconnect
                if self._mqttc:
                    if self._connected:
                         self._mqttc.publish(state_module.config['mqtt']['base_topic'] + '/status', state_module.config['mqtt']['offline'], retain=state_module.config['mqtt']['retain'])
                    self._mqttc.loop_stop()
                    self._mqttc.disconnect()
                    self._mqttc = None
        except Exception:
            logger.error('Fatal exception has occured', exc_info=True)
        finally:
            self._stopper.set()
