"""
S0PCM Reader Constants

Shared constants and enums for type safety across the application.
"""

from enum import StrEnum


class ConnectionStatus(StrEnum):
    """MQTT connection status values."""

    ONLINE = "online"
    OFFLINE = "offline"


class SerialPacketType(StrEnum):
    """Serial packet type identifiers."""

    HEADER = "/"
    DATA = "ID:"


class MqttTopicSuffix(StrEnum):
    """MQTT topic suffixes for meter data."""

    TOTAL = "total"
    TODAY = "today"
    YESTERDAY = "yesterday"
    PULSECOUNT = "pulsecount"
