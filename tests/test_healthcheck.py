"""
Tests for the healthcheck module.

Verifies process detection logic used by Docker HEALTHCHECK.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from healthcheck import is_process_running


def _mock_proc_entries(pids, cmdline_data=None, side_effect=None):
    """Create mock Path entries for /proc."""
    entries = []
    for pid in pids:
        entry = MagicMock(spec=Path)
        entry.name = pid
        cmdline_path = MagicMock(spec=Path)
        if side_effect:
            cmdline_path.read_bytes.side_effect = side_effect
        elif cmdline_data is not None:
            cmdline_path.read_bytes.return_value = cmdline_data
        entry.__truediv__ = MagicMock(return_value=cmdline_path)
        entries.append(entry)
    return entries


class TestIsProcessRunning:
    """Tests for the is_process_running function."""

    @patch("healthcheck.os.getpid", return_value=1)
    @patch("healthcheck.Path.iterdir")
    def test_process_found(self, mock_iterdir, mock_getpid):
        """Returns True when the target process is found in /proc."""
        cmdline_data = b"python3\x00/usr/src/s0pcm_reader.py\x00"
        mock_iterdir.return_value = _mock_proc_entries(["1", "42", "100"], cmdline_data=cmdline_data)

        assert is_process_running() is True

    @patch("healthcheck.os.getpid", return_value=1)
    @patch("healthcheck.Path.iterdir")
    def test_process_not_found(self, mock_iterdir, mock_getpid):
        """Returns False when the target process is not in /proc."""
        cmdline_data = b"python3\x00/usr/src/other_script.py\x00"
        mock_iterdir.return_value = _mock_proc_entries(["1", "42", "100"], cmdline_data=cmdline_data)

        assert is_process_running() is False

    @patch("healthcheck.os.getpid", return_value=42)
    @patch("healthcheck.Path.iterdir")
    def test_skips_own_pid(self, mock_iterdir, mock_getpid):
        """Skips the healthcheck's own PID to avoid false positives."""
        cmdline_data = b"python3\x00/usr/src/s0pcm_reader.py\x00"
        mock_iterdir.return_value = _mock_proc_entries(["42"], cmdline_data=cmdline_data)

        assert is_process_running() is False

    @patch("healthcheck.os.getpid", return_value=1)
    @patch("healthcheck.Path.iterdir")
    def test_skips_non_numeric_entries(self, mock_iterdir, mock_getpid):
        """Skips non-numeric /proc entries like 'self', 'net', etc."""
        mock_iterdir.return_value = _mock_proc_entries(["self", "net", "sys"])

        assert is_process_running() is False

    @patch("healthcheck.os.getpid", return_value=1)
    @patch("healthcheck.Path.iterdir")
    def test_handles_permission_error(self, mock_iterdir, mock_getpid):
        """Gracefully handles PermissionError when reading /proc/pid/cmdline."""
        mock_iterdir.return_value = _mock_proc_entries(["42"], side_effect=PermissionError)

        assert is_process_running() is False

    @patch("healthcheck.os.getpid", return_value=1)
    @patch("healthcheck.Path.iterdir", side_effect=OSError("No /proc"))
    def test_handles_missing_proc(self, mock_iterdir, mock_getpid):
        """Returns False when /proc is not available (e.g., non-Linux)."""
        assert is_process_running() is False

    @patch("healthcheck.os.getpid", return_value=1)
    @patch("healthcheck.Path.iterdir")
    def test_custom_process_name(self, mock_iterdir, mock_getpid):
        """Works with a custom process name argument."""
        cmdline_data = b"python3\x00/usr/src/custom_app.py\x00"
        mock_iterdir.return_value = _mock_proc_entries(["42"], cmdline_data=cmdline_data)

        assert is_process_running("custom_app.py") is True

        # Reset for second check
        mock_iterdir.return_value = _mock_proc_entries(["42"], cmdline_data=cmdline_data)
        assert is_process_running("other_app.py") is False
