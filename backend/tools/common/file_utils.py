from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_lines_to_tempfile(lines: list[str], suffix: str = ".txt") -> Path:
    """Write *lines* to a named temporary file and return its :class:`Path`.

    The caller is responsible for deleting the file when done::

        tmp = write_lines_to_tempfile(targets)
        try:
            run_command(["sometool", "-l", str(tmp)], timeout=60)
        finally:
            tmp.unlink(missing_ok=True)
    """
    fd, path_str = tempfile.mkstemp(suffix=suffix, prefix="recon_")
    path = Path(path_str)
    try:
        path.write_text("\n".join(lines), encoding="utf-8")
    finally:
        os.close(fd)
    return path
