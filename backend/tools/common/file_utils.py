from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path


@contextlib.contextmanager
def temp_output_file(prefix: str = "recon_", suffix: str = ".txt") -> Iterator[Path]:
    """Yield a path to a fresh temp file, deleting it on exit.

    The file is created empty and closed so an external tool can stream its
    stdout into it::

        with temp_output_file(prefix="gau_") as out:
            runner.run_to_file(hosts, out)
            urls = deduplicate_file(out)
    """
    fd, path_str = tempfile.mkstemp(suffix=suffix, prefix=prefix)
    os.close(fd)
    path = Path(path_str)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


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
