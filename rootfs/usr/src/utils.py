"""
S0PCM Reader Utilities

Helper functions for version detection and Home Assistant Supervisor API access.
"""

import os
import json
import logging
import urllib.request

import yaml

logger = logging.getLogger(__name__)


def get_version():
    """
    Get the S0PCM Reader version.
    
    Priority:
    1. S0PCM_READER_VERSION environment variable (set by HA addon)
    2. config.yaml in common locations (for local development)
    3. 'dev' as fallback
    """
    # 1. Try environment variable (provided by HA addon startup)
    version = os.getenv('S0PCM_READER_VERSION')
    if version:
        return version

    # 2. Try to read from config.yaml (for local development)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    search_paths = [
        os.path.join(script_dir, '../../../config.yaml'),  # Local repo structure
        os.path.join(script_dir, '../../config.yaml'),
        os.path.join(script_dir, 'config.yaml'),
        './config.yaml'
    ]

    for path in search_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    config_yaml = yaml.safe_load(f)
                    if config_yaml and 'version' in config_yaml:
                        return f"{config_yaml['version']} (local)"
            except Exception:
                pass
    
    return 'dev'


def get_supervisor_config(service):
    """
    Fetch service configuration from the Home Assistant Supervisor API.
    
    Args:
        service: The service name (e.g., 'mqtt')
        
    Returns:
        dict: Service configuration data, or empty dict on failure
    """
    token = os.getenv('SUPERVISOR_TOKEN')
    if not token:
        return {}

    url = f"http://supervisor/services/{service}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                return data.get('data', {})
    except Exception as e:
        logger.debug(f"Supervisor API discovery for {service} failed: {e}")
    return {}


# Backwards compatibility aliases
GetVersion = get_version
GetSupervisorConfig = get_supervisor_config
