"""
S0PCM Reader Utilities

Helper functions for version detection and Home Assistant Supervisor API access.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

import yaml

logger = logging.getLogger(__name__)

# Type Aliases
type JsonDict = dict[str, Any]


def get_version() -> str:
    """
    Get the S0PCM Reader version.

    Priority:
    1. S0PCM_READER_VERSION environment variable (set by HA app)
    2. config.yaml in common locations (for local development)
    3. 'dev' as fallback

    Returns:
        str: The version string.
    """
    # 1. Try environment variable (provided by HA app startup)
    version = os.getenv("S0PCM_READER_VERSION")
    if version:
        return version

    # 2. Try to read from config.yaml (for local development)
    script_path = Path(__file__).resolve()
    script_dir = script_path.parent
    search_paths = [
        script_dir / "../../../config.yaml",  # Local repo structure
        script_dir / "../../config.yaml",
        script_dir / "config.yaml",
        Path("./config.yaml"),
    ]

    for path in search_paths:
        if path.exists():
            try:
                with path.open() as f:
                    if (config_yaml := yaml.safe_load(f)) and "version" in config_yaml:
                        return f"{config_yaml['version']} (local)"
            except OSError, yaml.YAMLError:
                pass

    return "dev"


def get_supervisor_config(service: str) -> JsonDict:
    """
    Fetch service configuration from the Home Assistant Supervisor API.

    Args:
        service: The service name (e.g., 'mqtt')

    Returns:
        JsonDict: Service configuration data, or empty dict on failure.
    """
    token = os.getenv("SUPERVISOR_TOKEN")
    if not token:
        return {}

    url = f"http://supervisor/services/{service}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                return data.get("data", {})
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        logger.debug(f"Supervisor API discovery for {service} failed: {e}")
    return {}


def parse_localized_number(value_str: str) -> float | None:
    """
    Parse a number string that might contain localized separators (US vs EU).

    Handles:
    - 1,000.50 (US/UK) -> 1000.5
    - 1.000,50 (EU/DE) -> 1000.5
    - 1000,5   (Mixed) -> 1000.5
    - 1000     (Int)   -> 1000.0

    Args:
        value_str: The string to parse.

    Returns:
        float | None: The parsed float, or None if parsing failed.
    """
    if not value_str:
        return None

    # Robust cleaning
    clean_state = value_str
    for unit in ["m³", "m3", "kwh", "l/min", "l"]:
        if unit in clean_state:
            clean_state = clean_state.replace(unit, "")

    clean_state = "".join(c for c in clean_state if c.isdigit() or c in ".,-")

    # Detect format based on separators
    dot_count = clean_state.count(".")
    comma_count = clean_state.count(",")

    if dot_count > 1 or comma_count > 1 or (dot_count == 1 and comma_count == 1):
        # Multiple separators or mixed separators
        if comma_count > dot_count:
            # Likely 1,000,000.00 (or 1,000.50)
            clean_state = clean_state.replace(",", "")
        elif dot_count > comma_count:
            # Likely 1.000.000,00
            clean_state = clean_state.replace(".", "").replace(",", ".")
        elif dot_count == 1 and comma_count == 1:
            # Ambiguous single separators: 1,000.50 vs 1.000,50
            if clean_state.find(".") < clean_state.find(","):
                # Dot first -> 1.000,50 (EU)
                clean_state = clean_state.replace(".", "").replace(",", ".")
            else:
                # Comma first -> 1,000.50 (US)
                clean_state = clean_state.replace(",", "")
        else:
            # Chaos (e.g. 1.1.1,1,1), strip all non-digits aggressively?
            # For now, just strip dots and commas to be safeish (likely integer)
            clean_state = clean_state.replace(".", "").replace(",", "")

    elif comma_count == 1 and "." not in clean_state:
        # Single comma, no dot -> 1,5 or 1000,5 -> treat as decimal separator
        clean_state = clean_state.replace(",", ".")

    try:
        if not clean_state.strip():
            return None
        return float(clean_state)
    except ValueError, TypeError:
        return None
