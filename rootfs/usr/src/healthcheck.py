"""
S0PCM Reader Healthcheck

Lightweight healthcheck script for Docker HEALTHCHECK.
Scans /proc to verify the main s0pcm_reader.py process is running.
Exit code 0 = healthy, 1 = unhealthy.
"""

import os
from pathlib import Path
import sys

PROCESS_NAME = "s0pcm_reader.py"


def is_process_running(process_name: str = PROCESS_NAME) -> bool:
    """Check if a process with the given name is running by scanning /proc."""
    my_pid = str(os.getpid())

    try:
        for entry in Path("/proc").iterdir():
            pid = entry.name
            if not pid.isdigit() or pid == my_pid:
                continue
            try:
                cmdline = (entry / "cmdline").read_bytes().decode("utf-8", errors="replace")
                if process_name in cmdline:
                    return True
            except OSError, PermissionError:
                continue
    except OSError:
        return False

    return False


if __name__ == "__main__":
    sys.exit(0 if is_process_running() else 1)
