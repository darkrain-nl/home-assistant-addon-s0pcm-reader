"""State recovery from retained MQTT messages and HA REST API."""

import asyncio
import datetime
import json
import logging
import os
import re
from typing import Any
import urllib.request

import aiomqtt

import state as state_module
import utils

logger = logging.getLogger(__name__)

# Type aliases for entity state collections.
type EntityStateList = list[dict[str, Any]]


class StateRecoverer:
    """Orchestrate state recovery phase during startup."""

    def __init__(self, context: state_module.AppContext, client: aiomqtt.Client):
        self.client = client
        self.recovered_data = {}
        self.recovered_names = {}
        self.context = context

    async def fetch_ha_state(self, entity_id: str) -> str | None:
        """Fetch state for an entity from Home Assistant REST API."""
        token = os.getenv("SUPERVISOR_TOKEN")
        if not token:
            return None

        url = f"http://supervisor/core/api/states/{entity_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            req = urllib.request.Request(url, headers=headers)

            def _fetch():
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode())
                        state = data.get("state")
                        if state not in [None, "unknown", "unavailable"]:
                            return state
                return None

            return await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.debug(f"HA API state fetch for {entity_id} failed: {e}")
        return None

    async def fetch_all_ha_states(self) -> EntityStateList:
        """Fetch all entity states from Home Assistant REST API."""
        token = os.getenv("SUPERVISOR_TOKEN")
        if not token:
            return []

        url = "http://supervisor/core/api/states"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            req = urllib.request.Request(url, headers=headers)

            def _fetch():
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        return json.loads(response.read().decode())
                return []

            return await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.debug(f"HA API fetch all states failed: {e}")
        return []

    def _process_message(self, topic: str, payload: bytes) -> None:
        """Parse retained MQTT messages to reconstruct meter state."""
        base_topic = self.context.config.mqtt.base_topic
        try:
            # Extract custom meter names from discovery config topics.
            if "/config" in topic:
                decoded = json.loads(payload.decode())
                unique_id = decoded.get("unique_id", "")
                state_topic = decoded.get("state_topic", "")

                match_id = re.search(rf"s0pcm_{base_topic}_(\d+)", unique_id)
                if match_id:
                    meter_id = int(match_id.group(1))
                    name_part = state_topic.replace(f"{base_topic}/", "")
                    name = name_part.split("/")[0]
                    if name and name != str(meter_id) and name.lower() != "none":
                        self.recovered_names[meter_id] = name
                        logger.debug(f"Recovery: Mapped ID {meter_id} to Name '{name}'")
                return

            # Extract counter values from measurement topics.
            topic_parts = topic.split("/")
            if len(topic_parts) >= 3:
                suffix = topic_parts[-1]
                if suffix in ["total", "today", "yesterday", "pulsecount"]:
                    identifier = topic_parts[-2]
                    try:
                        value = int(float(payload.decode()))
                        self.recovered_data.setdefault(identifier, {})[suffix] = value
                    except ValueError:
                        pass

            if topic.endswith("/date"):
                try:
                    dt = datetime.date.fromisoformat(payload.decode())
                    self.context.state.date = dt
                except ValueError:
                    pass
        except Exception as e:
            logger.debug(f"Recovery parse error: {e}")

    async def run(self):
        """Run recovery subscriptions and state reconciliation."""
        logger.info("Starting State Recovery phase...")
        base_topic = self.context.config.mqtt.base_topic
        discovery_prefix = self.context.config.mqtt.discovery_prefix

        # Subscribe to retained topics to reconstruct history.
        topics = [
            f"{base_topic}/+/total",
            f"{base_topic}/+/today",
            f"{base_topic}/+/yesterday",
            f"{base_topic}/+/pulsecount",
            f"{base_topic}/date",
            f"{discovery_prefix}/sensor/{base_topic}/#",
        ]
        for t in topics:
            await self.client.subscribe(t)

        wait_time = self.context.config.mqtt.recovery_wait
        logger.info(f"Recovery: Waiting {wait_time}s for MQTT retained messages...")

        # Collect retained messages before timeout expires.
        try:
            async with asyncio.timeout(wait_time):
                async for message in self.client.messages:
                    self._process_message(str(message.topic), message.payload)
        except TimeoutError:
            pass

        # Unsubscribe from recovery topics.
        for t in topics:
            await self.client.unsubscribe(t)

        # Populate counters from recovered MQTT numeric topics.
        for id_str, data in self.recovered_data.items():
            try:
                meter_id = int(id_str)
            except ValueError:
                continue

            if any(data.get(k, 0) > 0 for k in ["total", "today", "pulsecount", "yesterday"]):
                if meter_id not in self.context.state.meters:
                    self.context.state.meters[meter_id] = state_module.MeterState()

                meter = self.context.state.meters[meter_id]
                meter.total = data.get("total", meter.total)
                meter.today = data.get("today", meter.today)
                meter.yesterday = data.get("yesterday", meter.yesterday)
                meter.pulsecount = data.get("pulsecount", meter.pulsecount)

        # Map custom names and name-based topic measurements.
        for mid, name in self.recovered_names.items():
            if mid not in self.context.state.meters:
                self.context.state.meters[mid] = state_module.MeterState()

            meter = self.context.state.meters[mid]
            meter.name = name

            if name in self.recovered_data:
                meter.total = max(meter.total, self.recovered_data[name].get("total", 0))
                meter.today = max(meter.today, self.recovered_data[name].get("today", 0))
                meter.yesterday = max(meter.yesterday, self.recovered_data[name].get("yesterday", 0))
                meter.pulsecount = max(meter.pulsecount, self.recovered_data[name].get("pulsecount", 0))

        # Query Home Assistant REST API when MQTT history is missing.
        ha_states = None
        for mid, meter in self.context.state.meters.items():
            if meter.total == 0:
                if ha_states is None:
                    logger.info(f"Recovery: Meter {mid} not found on MQTT, attempting HA API fallback...")
                    ha_states = await self.fetch_all_ha_states()

                found_val = self._find_total_in_ha(mid, ha_states)
                if found_val is not None:
                    meter.total = found_val
                    logger.info(f"Recovery: Recovered total for meter {mid} from HA API: {found_val}")

        # Log recovered metrics for observability.
        for mid, meter in self.context.state.meters.items():
            logger.info(f"Recovered total for meter {mid}: {meter.total}")
            logger.info(f"Recovered pulsecount for meter {mid}: {meter.pulsecount}")
            logger.info(f"Recovered today for meter {mid}: {meter.today}")
            logger.info(f"Recovered yesterday for meter {mid}: {meter.yesterday}")

        logger.info("State Recovery complete.")

    def _find_total_in_ha(self, mid: int, ha_states: EntityStateList) -> int | None:
        """Search Home Assistant entities for matching meter total."""
        base_topic = self.context.config.mqtt.base_topic
        meter = self.context.state.meters.get(mid)
        name = meter.name if meter else None

        # Build potential entity ID patterns.
        patterns = [f"sensor.{base_topic}_{mid}_total", f"sensor.s0pcm_reader_{mid}_total", f"sensor.{mid}_total"]
        if name:
            sanitized_name = name.lower().replace(" ", "_")
            patterns.insert(0, f"sensor.{base_topic}_{sanitized_name}_total")
            patterns.insert(1, f"sensor.{sanitized_name}_total")

        for p in patterns:
            for s in ha_states:
                if s.get("entity_id") == p:
                    state_str = str(s.get("state", "")).lower()
                    if state_str in [None, "unknown", "unavailable", ""]:
                        continue

                    # Parse localized number string.
                    parsed_val = utils.parse_localized_number(state_str)
                    if parsed_val is not None:
                        return int(parsed_val)

        return None
