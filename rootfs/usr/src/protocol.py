"""
S0PCM Protocol Parser

This module handles parsing of S0PCM (S0 Pulse Counter Module) serial protocol packets.

Protocol Format:
- Header: /ID:S0 Pulse Counter V0.6 - 30/30/30/30/30ms
- Data (S0PCM-5): ID:a:I:b:M1:c:d:M2:e:f:M3:g:h:M4:i:j:M5:k:l
- Data (S0PCM-2): ID:a:I:b:M1:c:d:M2:e:f

Where:
- a = Unique ID of the S0PCM
- b = Interval between telegrams (seconds)
- c/e/g/i/k = Pulses in last interval for meter 1/2/3/4/5
- d/f/h/j/l = Total pulses since startup for meter 1/2/3/4/5
"""




def parse_s0pcm_packet(datastr: str) -> dict[int, dict[str, int]]:
    """
    Parse a raw S0PCM data packet string.

    Args:
        datastr: The raw data string from the serial port (e.g. "ID:8237:I:10:M1:0:100...")

    Returns:
        dict[int, dict[str, int]]: A dictionary of parsed meter data where keys are meter IDs (1-5) and values
              are dictionaries containing 'pulsecount'.
              Example: {1: {'pulsecount': 100}, 2: {'pulsecount': 50}}

    Raises:
        ValueError: If the packet format is invalid or values cannot be parsed.
    """
    # Split data into an array
    s0arr = datastr.split(':')
    size = 0

    # s0pcm-5 (19 parts) or s0pcm-2 (10 parts)
    if len(s0arr) == 19:
        size = 5
    elif len(s0arr) == 10:
        size = 2
    else:
        raise ValueError(f"Packet has invalid length: Expected 10 or 19 parts, got {len(s0arr)}")

    result = {}

    # Loop through 2/5 s0pcm data
    for count in range(1, size + 1):
        offset = 4 + ((count - 1) * 3)

        # expected format: M1:x:x
        expected_marker = 'M' + str(count)
        if s0arr[offset] != expected_marker:
            raise ValueError(f"Expecting '{expected_marker}', received '{s0arr[offset]}'")

        try:
            pulsecount = int(s0arr[offset + 2])
        except ValueError:
            raise ValueError(f"Cannot convert pulsecount '{s0arr[offset + 2]}' into integer for meter {count}")

        result[count] = {'pulsecount': pulsecount}

    return result
