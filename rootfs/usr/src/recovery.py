"""
Recovery Module

Handles state recovery from MQTT retained messages and Home Assistant REST API.
"""

import json
import logging
import re
import urllib.request
import os
import datetime
import time
from typing import Dict, List, Any, Optional

import paho.mqtt.client as mqtt
import state as state_module

logger = logging.getLogger(__name__)

class StateRecoverer:
    """Helper class to manage the startup state recovery phase."""

    def __init__(self, mqttc: mqtt.Client):
        self.mqttc = mqttc
        self.recovered_data = {} # {identifier: {'total': X}}
        self.recovered_names = {} # {id: name}
        self.context = state_module.get_context()

    def fetch_ha_state(self, entity_id: str) -> Optional[str]:
        """Fetch the current state of an entity from Home Assistant."""
        token = os.getenv('SUPERVISOR_TOKEN')
        if not token: return None

        url = f"http://supervisor/core/api/states/{entity_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
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

    def fetch_all_ha_states(self) -> List[Dict[str, Any]]:
        """Fetch all entity states from Home Assistant."""
        token = os.getenv('SUPERVISOR_TOKEN')
        if not token: return []

        url = "http://supervisor/core/api/states"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    return json.loads(response.read().decode())
        except Exception as e:
            logger.debug(f"HA API fetch all states failed: {e}")
        return []

    def on_message(self, client, userdata, msg):
        """Process messages for state recovery."""
        base_topic = self.context.config['mqtt']['base_topic']
        try:
            # 1. Discovery topics (Name Mapping)
            if '/config' in msg.topic:
                payload = json.loads(msg.payload.decode())
                unique_id = payload.get('unique_id', '')
                state_topic = payload.get('state_topic', '')
                
                match_id = re.search(fr"s0pcm_{base_topic}_(\d+)", unique_id)
                if match_id:
                    meter_id = int(match_id.group(1))
                    name_part = state_topic.replace(f"{base_topic}/", "")
                    name = name_part.split('/')[0]
                    if name and name != str(meter_id) and name.lower() != 'none':
                        self.recovered_names[meter_id] = name
                        logger.debug(f"Recovery: Mapped ID {meter_id} to Name '{name}'")
                return

            # 2. Data topics
            topic_parts = msg.topic.split('/')
            if len(topic_parts) >= 3:
                suffix = topic_parts[-1]
                if suffix in ['total', 'today', 'yesterday', 'pulsecount']:
                    identifier = topic_parts[-2]
                    try:
                        value = int(float(msg.payload.decode()))
                        self.recovered_data.setdefault(identifier, {})[suffix] = value
                    except ValueError: pass
            
            if msg.topic.endswith('/date'):
                try:
                    dt = datetime.date.fromisoformat(msg.payload.decode())
                    with self.context.lock:
                        self.context.state.date = dt
                except ValueError: pass
        except Exception as e:
            logger.debug(f"Recovery parse error: {e}")

    def run(self):
        """Execute the recovery process."""
        logger.info("Starting State Recovery phase...")
        base_topic = self.context.config['mqtt']['base_topic']
        discovery_prefix = self.context.config['mqtt']['discovery_prefix']

        # Temporarily steal on_message
        original_on_message = self.mqttc.on_message
        self.mqttc.on_message = self.on_message

        # Subscribe to recovery topics
        topics = [
            f"{base_topic}/+/total", f"{base_topic}/+/today", 
            f"{base_topic}/+/yesterday", f"{base_topic}/+/pulsecount",
            f"{base_topic}/date", f"{discovery_prefix}/sensor/{base_topic}/#"
        ]
        for t in topics: self.mqttc.subscribe(t)

        logger.info("Recovery: Waiting 7s for MQTT retained messages...")
        time.sleep(7)

        # Cleanup subscriptions
        for t in topics: self.mqttc.unsubscribe(t)
        self.mqttc.on_message = original_on_message

        # Sync mapped data
        with self.context.lock:
            # First pass: direct IDs
            for i in range(1, 6):
                id_str = str(i)
                if id_str in self.recovered_data:
                    data = self.recovered_data[id_str]
                    # Only initialize if there is actually data beyond zeroes
                    if any(data.get(k, 0) > 0 for k in ['total', 'today', 'pulsecount', 'yesterday']):
                        if i not in self.context.state.meters:
                            self.context.state.meters[i] = state_module.MeterState()
                        
                        meter = self.context.state.meters[i]
                        meter.total = data.get('total', meter.total)
                        meter.today = data.get('today', meter.today)
                        meter.yesterday = data.get('yesterday', meter.yesterday)
                        meter.pulsecount = data.get('pulsecount', meter.pulsecount)
            
            # Second pass: Names (only if ID was already found or if name is solid)
            for mid, name in self.recovered_names.items():
                if mid not in self.context.state.meters:
                    self.context.state.meters[mid] = state_module.MeterState()
                
                meter = self.context.state.meters[mid]
                meter.name = name
                
                # Check for data under the name topic too (split_topic format)
                if name in self.recovered_data:
                    meter.total = max(meter.total, self.recovered_data[name].get('total', 0))
                    meter.today = max(meter.today, self.recovered_data[name].get('today', 0))
                    meter.yesterday = max(meter.yesterday, self.recovered_data[name].get('yesterday', 0))
                    meter.pulsecount = max(meter.pulsecount, self.recovered_data[name].get('pulsecount', 0))

            # HA API Fallback for missing totals
            ha_states = None
            for mid, meter in self.context.state.meters.items():
                if meter.total == 0:
                    if ha_states is None: 
                        logger.info(f"Recovery: Meter {mid} not found on MQTT, attempting HA API fallback...")
                        ha_states = self.fetch_all_ha_states()
                    
                    found_val = self._find_total_in_ha(mid, ha_states)
                    if found_val is not None:
                        meter.total = found_val
                        logger.info(f"Recovery: Recovered total for meter {mid} from HA API: {found_val}")

            # Baseline share
            self.context.state_share = self.context.state.model_copy(deep=True)
            
            # Summary logging (Useful for verification)
            for mid, meter in self.context.state.meters.items():
                logger.info(f"Recovered total for meter {mid}: {meter.total}")
                logger.info(f"Recovered pulsecount for meter {mid}: {meter.pulsecount}")
                logger.info(f"Recovered today for meter {mid}: {meter.today}")
                logger.info(f"Recovered yesterday for meter {mid}: {meter.yesterday}")
        
        logger.info("State Recovery complete.")

    def _find_total_in_ha(self, mid: int, ha_states: List[Dict[str, Any]]) -> Optional[int]:
        """Surgically find the total for a meter in a list of HA states."""
        base_topic = self.context.config['mqtt']['base_topic']
        name = self.context.state.meters[mid].name
        
        # Patterns to check
        patterns = [
            f"sensor.{base_topic}_{mid}_total",
            f"sensor.s0pcm_reader_{mid}_total",
            f"sensor.{mid}_total"
        ]
        if name:
            sanitized_name = name.lower().replace(" ", "_")
            patterns.insert(0, f"sensor.{base_topic}_{sanitized_name}_total")
            patterns.insert(1, f"sensor.{sanitized_name}_total")

        for p in patterns:
            for s in ha_states:
                if s.get('entity_id') == p:
                    state_str = str(s.get('state', '')).lower()
                    if state_str in [None, 'unknown', 'unavailable', '']: continue

                    # Robust cleaning (mirrors old logic)
                    clean_state = state_str
                    for unit in ['m³', 'm3', 'kwh', 'l/min', 'l']:
                        if unit in clean_state: clean_state = clean_state.replace(unit, '')
                    
                    clean_state = "".join(c for c in clean_state if c.isdigit() or c in '.,-')
                    
                    if clean_state.count('.') > 1 or clean_state.count(',') > 1 or (clean_state.count('.') == 1 and clean_state.count(',') == 1):
                        clean_state = clean_state.replace('.', '').replace(',', '')
                    elif clean_state.count(',') == 1 and '.' not in clean_state:
                        clean_state = clean_state.replace(',', '.')
                    
                    clean_state = clean_state.strip()

                    try:
                        if not clean_state: continue
                        return int(float(clean_state))
                    except (ValueError, TypeError): pass
        return None
