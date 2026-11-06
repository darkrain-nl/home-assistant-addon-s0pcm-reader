"""Unit tests for shared constants and enums."""

import pytest

from constants import ConnectionStatus, MqttTopicSuffix, SerialPacketType


class TestConnectionStatus:
    def test_enum_values(self):
        """Test ConnectionStatus enum has correct values."""
        assert ConnectionStatus.ONLINE.value == "online"
        assert ConnectionStatus.OFFLINE.value == "offline"

    def test_enum_membership(self):
        """Test enum membership and iteration."""
        assert "ONLINE" in ConnectionStatus.__members__
        assert "OFFLINE" in ConnectionStatus.__members__
        assert len(list(ConnectionStatus)) == 2

    def test_string_comparison(self):
        """Test that enum values work in string comparisons."""
        status = ConnectionStatus.ONLINE
        assert status == "online"
        assert str(status) == "online"


class TestSerialPacketType:
    def test_enum_values(self):
        """Test SerialPacketType enum has correct values."""
        assert SerialPacketType.HEADER.value == "/"
        assert SerialPacketType.DATA.value == "ID:"

    def test_enum_membership(self):
        """Test enum membership."""
        assert "HEADER" in SerialPacketType.__members__
        assert "DATA" in SerialPacketType.__members__
        assert len(list(SerialPacketType)) == 2

    def test_startswith_usage(self):
        """Test enum values work with str.startswith()."""
        test_data = "/meter/data"
        assert test_data.startswith(SerialPacketType.HEADER)

        test_id = "ID:123"
        assert test_id.startswith(SerialPacketType.DATA)


class TestMqttTopicSuffix:
    def test_enum_values(self):
        """Test MqttTopicSuffix enum has correct values."""
        assert MqttTopicSuffix.TOTAL.value == "total"
        assert MqttTopicSuffix.TODAY.value == "today"
        assert MqttTopicSuffix.YESTERDAY.value == "yesterday"
        assert MqttTopicSuffix.PULSECOUNT.value == "pulsecount"

    def test_enum_membership(self):
        """Test enum membership."""
        assert "TOTAL" in MqttTopicSuffix.__members__
        assert "TODAY" in MqttTopicSuffix.__members__
        assert "YESTERDAY" in MqttTopicSuffix.__members__
        assert "PULSECOUNT" in MqttTopicSuffix.__members__
        assert len(list(MqttTopicSuffix)) == 4

    def test_iteration(self):
        """Test that we can iterate over enum."""
        suffixes = [MqttTopicSuffix.TOTAL, MqttTopicSuffix.TODAY, MqttTopicSuffix.YESTERDAY]
        assert all(isinstance(s, str) for s in suffixes)
        assert len(suffixes) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
