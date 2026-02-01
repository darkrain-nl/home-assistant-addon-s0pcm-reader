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
            except (OSError, yaml.YAMLError):
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
