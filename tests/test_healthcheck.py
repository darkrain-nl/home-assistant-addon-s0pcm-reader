"""
Tests for the healthcheck module.

Verifies process detection logic used by Docker HEALTHCHECK.
"""

from unittest.mock import mock_open, patch

from healthcheck import is_process_running


class TestIsProcessRunning:
    """Tests for the is_process_running function."""

    @patch("healthcheck.os.getpid", return_value=1)
    @patch("healthcheck.os.listdir")
    def test_process_found(self, mock_listdir, mock_getpid):
        """Returns True when the target process is found in /proc."""
        mock_listdir.return_value = ["1", "42", "100"]

        cmdline_data = b"python3\x00/usr/src/s0pcm_reader.py\x00"
        with patch("builtins.open", mock_open(read_data=cmdline_data)):
            assert is_process_running() is True

    @patch("healthcheck.os.getpid", return_value=1)
    @patch("healthcheck.os.listdir")
    def test_process_not_found(self, mock_listdir, mock_getpid):
        """Returns False when the target process is not in /proc."""
        mock_listdir.return_value = ["1", "42", "100"]

        cmdline_data = b"python3\x00/usr/src/other_script.py\x00"
        with patch("builtins.open", mock_open(read_data=cmdline_data)):
            assert is_process_running() is False

    @patch("healthcheck.os.getpid", return_value=42)
    @patch("healthcheck.os.listdir")
    def test_skips_own_pid(self, mock_listdir, mock_getpid):
        """Skips the healthcheck's own PID to avoid false positives."""
        mock_listdir.return_value = ["42"]

        # Even if cmdline matches, own PID should be skipped
        cmdline_data = b"python3\x00/usr/src/s0pcm_reader.py\x00"
        with patch("builtins.open", mock_open(read_data=cmdline_data)):
            assert is_process_running() is False

    @patch("healthcheck.os.getpid", return_value=1)
    @patch("healthcheck.os.listdir")
    def test_skips_non_numeric_entries(self, mock_listdir, mock_getpid):
        """Skips non-numeric /proc entries like 'self', 'net', etc."""
        mock_listdir.return_value = ["self", "net", "sys"]

        assert is_process_running() is False

    @patch("healthcheck.os.getpid", return_value=1)
    @patch("healthcheck.os.listdir")
    def test_handles_permission_error(self, mock_listdir, mock_getpid):
        """Gracefully handles PermissionError when reading /proc/pid/cmdline."""
        mock_listdir.return_value = ["42"]

        with patch("builtins.open", side_effect=PermissionError):
            assert is_process_running() is False

    @patch("healthcheck.os.getpid", return_value=1)
    @patch("healthcheck.os.listdir", side_effect=OSError("No /proc"))
    def test_handles_missing_proc(self, mock_listdir, mock_getpid):
        """Returns False when /proc is not available (e.g., non-Linux)."""
        assert is_process_running() is False

    @patch("healthcheck.os.getpid", return_value=1)
    @patch("healthcheck.os.listdir")
    def test_custom_process_name(self, mock_listdir, mock_getpid):
        """Works with a custom process name argument."""
        mock_listdir.return_value = ["42"]

        cmdline_data = b"python3\x00/usr/src/custom_app.py\x00"
        with patch("builtins.open", mock_open(read_data=cmdline_data)):
            assert is_process_running("custom_app.py") is True
            assert is_process_running("other_app.py") is False
