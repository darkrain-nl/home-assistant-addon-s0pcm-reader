"""
Tests for the refactored packet parsing logic.
This test files targets the standalone 'parse_s0pcm_packet' function.
"""
import pytest
from protocol import parse_s0pcm_packet

class TestPacketParsing:
    """Test S0PCM packet parsing logic."""

    def test_parse_s0pcm2_packet(self):
        """Test parsing valid S0PCM-2 data packet."""
        # Format: ID:ID:I:Interval:M1:Count:Pulse:M2:Count:Pulse
        data_str = "ID:8237:I:10:M1:0:100:M2:0:50"
        
        result = parse_s0pcm_packet(data_str)
        
        # Should return data for 2 meters
        assert len(result) == 2
        assert 1 in result
        assert 2 in result
        
        # Verify pulse counts
        assert result[1]['pulsecount'] == 100
        assert result[2]['pulsecount'] == 50

    def test_parse_s0pcm5_packet(self):
        """Test parsing valid S0PCM-5 data packet."""
        # Format: ID:ID:I:Interval:M1:x:x:M2:x:x:M3:x:x:M4:x:x:M5:x:x
        data_str = "ID:8237:I:10:M1:0:100:M2:0:50:M3:0:25:M4:0:75:M5:0:10"
        
        result = parse_s0pcm_packet(data_str)
        
        # Should return data for 5 meters
        assert len(result) == 5
        for i in range(1, 6):
            assert i in result
        
        # Verify specific values
        assert result[1]['pulsecount'] == 100
        assert result[3]['pulsecount'] == 25
        assert result[5]['pulsecount'] == 10

    def test_invalid_length(self):
        """Test handling of packets with invalid number of parts."""
        # Too short
        with pytest.raises(ValueError, match="Packet has invalid length"):
            parse_s0pcm_packet("ID:8237:I:10:M1:0:100")
            
        # Too long
        with pytest.raises(ValueError, match="Packet has invalid length"):
            parse_s0pcm_packet("ID:8237:I:10:M1:0:100:M2:0:50:M3:0:25")

    def test_invalid_markers(self):
        """Test handling of packets with incorrect markers."""
        # M1 marker missing/wrong
        with pytest.raises(ValueError, match="Expecting 'M1'"):
            parse_s0pcm_packet("ID:8237:I:10:X1:0:100:M2:0:50")

    def test_non_integer_pulsecount(self):
        """Test handling of non-integer pulse counts."""
        with pytest.raises(ValueError, match="Cannot convert pulsecount"):
            parse_s0pcm_packet("ID:8237:I:10:M1:0:ABC:M2:0:50")

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
