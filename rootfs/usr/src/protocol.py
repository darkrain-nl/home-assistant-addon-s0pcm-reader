"""Parser for S0PCM serial telegram data packets."""

from typing import TypeGuard

# Type aliases for parsed packet dictionaries.
type MeterResult = dict[str, int | dict[int, dict[str, int]]]


def is_valid_packet_length(arr: list[str]) -> TypeGuard[list[str]]:
    """Validate packet length for 2-channel or 5-channel models."""
    return len(arr) in (10, 19)


def parse_s0pcm_packet(datastr: str) -> MeterResult:
    """Parse raw S0PCM telegram into structured meter counter dict."""
    s0arr = datastr.split(":")
    size = 0

    if not is_valid_packet_length(s0arr):
        raise ValueError(f"Packet has invalid length: Expected 10 or 19 parts, got {len(s0arr)}")

    # 19 parts for S0PCM-5, 10 parts for S0PCM-2.
    if len(s0arr) == 19:
        size = 5
    elif len(s0arr) == 10:
        size = 2

    # Extract telegram interval.
    try:
        interval = int(s0arr[3])
    except IndexError, ValueError:
        raise ValueError(f"Cannot parse interval from packet: '{datastr}'") from None

    result = {"interval": interval, "meters": {}}

    # Parse counters for each channel.
    for count in range(1, size + 1):
        offset = 4 + ((count - 1) * 3)

        # Validate channel marker prefix.
        expected_marker = "M" + str(count)
        if s0arr[offset] != expected_marker:
            raise ValueError(f"Expecting '{expected_marker}', received '{s0arr[offset]}'")

        try:
            pulses_in_interval = int(s0arr[offset + 1])
            pulsecount = int(s0arr[offset + 2])
        except IndexError, ValueError:
            raise ValueError(f"Cannot convert values into integers for meter {count}") from None

        result["meters"][count] = {
            "pulses_in_interval": pulses_in_interval,
            "pulsecount": pulsecount,
        }

    return result
