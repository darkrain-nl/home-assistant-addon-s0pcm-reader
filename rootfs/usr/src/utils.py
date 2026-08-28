"""Version detection and Supervisor API helper utilities."""

import asyncio
import json
import logging
import os
from pathlib import Path
import re
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

import yaml

logger = logging.getLogger(__name__)

# Type aliases for JSON dictionaries.
type JsonDict = dict[str, Any]


async def get_version() -> str:
    """Detect application version from environment or config.yaml."""
    # Check environment variable set in container.
    version = os.getenv("S0PCM_READER_VERSION")
    if version:
        return version

    # Fallback to local config.yaml during development.
    script_path = Path(__file__).resolve()
    script_dir = script_path.parent
    search_paths = [
        script_dir / "../../../config.yaml",
        script_dir / "../../config.yaml",
        script_dir / "config.yaml",
        Path("./config.yaml"),
    ]

    def _read_version():
        for path in search_paths:
            if path.exists():
                try:
                    with path.open() as f:
                        if (config_yaml := yaml.safe_load(f)) and "version" in config_yaml:
                            return f"{config_yaml['version']} (local)"
                except OSError, yaml.YAMLError:
                    pass
        return None

    res = await asyncio.to_thread(_read_version)
    if res:
        return res

    return "dev"


async def get_supervisor_config(service: str) -> JsonDict:
    """Fetch service configuration dictionary from Supervisor API."""
    token = os.getenv("SUPERVISOR_TOKEN")
    if not token:
        return {}

    url = f"http://supervisor/services/{service}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        req = urllib.request.Request(url, headers=headers)

        def _fetch():
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    return data.get("data", {})
            return {}

        return await asyncio.to_thread(_fetch)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        logger.debug(f"Supervisor API discovery for {service} failed: {e}")
    return {}


def parse_localized_number(value_str: str) -> float | None:
    """Parse localized number strings containing dots or commas."""
    if not value_str:
        return None

    # Strip unit suffixes and retain numerical chars.
    clean_state = value_str
    for unit in ["m³", "m3", "kwh", "l/min", "l"]:
        if unit in clean_state:
            clean_state = clean_state.replace(unit, "")

    clean_state = "".join(c for c in clean_state if c.isdigit() or c in ".,-")

    # Normalize decimal and thousands separators.
    dot_count = clean_state.count(".")
    comma_count = clean_state.count(",")

    if dot_count > 1 or comma_count > 1 or (dot_count == 1 and comma_count == 1):
        if comma_count > dot_count:
            clean_state = clean_state.replace(",", "")
        elif dot_count > comma_count:
            clean_state = clean_state.replace(".", "").replace(",", ".")
        elif dot_count == 1 and comma_count == 1:
            if clean_state.find(".") < clean_state.find(","):
                clean_state = clean_state.replace(".", "").replace(",", ".")
            else:
                clean_state = clean_state.replace(",", "")
        else:
            # Multiple conflicting separators.
            clean_state = clean_state.replace(".", "").replace(",", "")

    elif comma_count == 1 and "." not in clean_state:
        # Single comma treated as decimal.
        clean_state = clean_state.replace(",", ".")

    try:
        if not clean_state.strip():
            return None
        return float(clean_state)
    except ValueError, TypeError:
        return None


async def get_ha_core_version() -> str | None:
    """Fetch Home Assistant Core version from Supervisor API."""
    token = os.getenv("SUPERVISOR_TOKEN")
    if not token:
        return None

    url = "http://supervisor/core/info"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        req = urllib.request.Request(url, headers=headers)

        def _fetch():
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    return data.get("data", {}).get("version")
            return None

        return await asyncio.to_thread(_fetch)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        logger.debug(f"Supervisor API /core/info failed: {e}")
    return None


def parse_ha_version(version_str: str | None) -> tuple[int, ...]:
    """Parse version string into integer tuple for comparison."""
    if not version_str:
        return (0, 0, 0)

    parts = version_str.split(".")
    parsed_parts = []
    for p in parts:
        match = re.match(r"^(\d+)", p)
        if match:
            parsed_parts.append(int(match.group(1)))
        else:
            parsed_parts.append(0)
    return tuple(parsed_parts)
