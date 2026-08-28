"""Process liveness probe for Docker container health checks."""

import os
from pathlib import Path
import sys

PROCESS_NAME = "s0pcm_reader.py"
PROCESS_INTERPRETER = "python"


def is_process_running(process_name: str = PROCESS_NAME) -> bool:
    """Verify main reader process is alive by inspecting /proc."""
    my_pid = str(os.getpid())

    try:
        for entry in Path("/proc").iterdir():
            pid = entry.name
            if not pid.isdigit() or pid == my_pid:
                continue
            try:
                cmdline = (entry / "cmdline").read_bytes().decode("utf-8", errors="replace")
                if process_name in cmdline and PROCESS_INTERPRETER in cmdline:
                    return True
            except OSError, PermissionError:
                continue
    except OSError:
        return False

    return False


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0 if is_process_running() else 1)
