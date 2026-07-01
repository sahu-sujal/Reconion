"""Temporary JavaScript download manager (Phase 6.1).

Downloaded JS is a *temporary processing artifact* — never kept on disk after a
batch is parsed. This manager:

  * downloads each JS URL into a private temp directory under
    ``/tmp/recon/js_processing/`` (streamed to disk, size-capped so a single
    huge/hostile file can't exhaust memory or disk),
  * retries transient download failures a bounded number of times,
  * maps each local file back to its originating JS URL so the worker can use
    the URL as the base for relative-endpoint resolution, and
  * **guarantees cleanup**: use it as a context manager, or call
    :meth:`cleanup` — the temp directory (downloaded JS + any tool scratch
    files) is removed even if processing raises.

Nothing about later reprocessing depends on these files: if endpoints must be
re-extracted, the caller simply downloads again from the stored JS URL. Storage
usage therefore stays constant regardless of how many JS files exist.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# Root for all temporary JS processing (per spec). Each batch gets a private
# subdirectory below this so concurrent batches never collide.
JS_PROCESSING_ROOT = Path(os.getenv("JS_PROCESSING_DIR", "/tmp/recon/js_processing"))

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
# Hard cap per file — JS bundles are large but a multi-hundred-MB "JS" file is
# almost certainly hostile or mislabeled. Bytes beyond the cap are discarded.
_MAX_FILE_BYTES = 15 * 1024 * 1024
_READ_CHUNK = 65_536
# Parallel downloads per batch (I/O-bound → threads give a large speedup over the
# previous one-at-a-time loop). Override with JS_DOWNLOAD_CONCURRENCY.
_DEFAULT_CONCURRENCY = int(os.getenv("JS_DOWNLOAD_CONCURRENCY", "20"))
# HTTP status codes that will never succeed on retry — don't waste attempts on
# them (the ortto.com gtm.js 404 storm was 3× retrying every missing file).
_PERMANENT_HTTP_STATUS = frozenset({400, 401, 403, 404, 405, 410, 451})


@dataclass(slots=True)
class DownloadedJs:
    """A successfully downloaded JS file and the URL it came from."""

    url: str
    path: Path
    js_file_id: object | None  # uuid.UUID | None — kept opaque to avoid import


class JsDownloadManager:
    """Download JS files into a private temp dir with guaranteed cleanup."""

    def __init__(
        self,
        timeout: int = 20,
        retries: int = 2,
        user_agent: str = _DEFAULT_USER_AGENT,
        concurrency: int = _DEFAULT_CONCURRENCY,
    ) -> None:
        self.timeout = timeout
        self.retries = max(0, retries)
        self.user_agent = user_agent
        self.concurrency = max(1, concurrency)
        JS_PROCESSING_ROOT.mkdir(parents=True, exist_ok=True)
        self._dir = Path(tempfile.mkdtemp(prefix="batch_", dir=str(JS_PROCESSING_ROOT)))

    # ------------------------------------------------------------------
    # Context manager — cleanup is guaranteed on exit
    # ------------------------------------------------------------------

    def __enter__(self) -> "JsDownloadManager":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()

    @property
    def work_dir(self) -> Path:
        return self._dir

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_batch(
        self,
        js_items: list[tuple[str, object | None]],
    ) -> tuple[list[DownloadedJs], list[str]]:
        """Download a batch of ``(js_url, js_file_id)`` pairs.

        Returns ``(succeeded, failed_urls)``. Failures are isolated — one bad
        URL never aborts the batch.
        """
        if not js_items:
            return [], []

        succeeded: list[DownloadedJs] = []
        failed: list[str] = []

        def _fetch(item: tuple[str, object | None]):
            url, js_file_id = item
            return item, self._download_one(url)

        # Downloads are network I/O-bound — run them concurrently. Pool size is
        # capped at the batch size so tiny batches don't spin up idle threads.
        workers = min(self.concurrency, len(js_items))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for (url, js_file_id), path in pool.map(_fetch, js_items):
                if path is not None:
                    succeeded.append(DownloadedJs(url=url, path=path, js_file_id=js_file_id))
                else:
                    failed.append(url)
        return succeeded, failed

    def _download_one(self, url: str) -> Path | None:
        """Download a single JS URL. Returns None on failure.

        Retries only *transient* failures (timeouts, connection errors, 5xx /
        429). Permanent HTTP errors (404/403/410/…) fail immediately — retrying
        them is pure wasted time and network.
        """
        target = self._dir / self._safe_filename(url)
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                self._stream_to_file(url, target)
                return target
            except HTTPError as exc:
                last_err = exc
                target.unlink(missing_ok=True)
                if exc.code in _PERMANENT_HTTP_STATUS:
                    break  # will never succeed — don't retry
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
            except (URLError, TimeoutError, OSError, ValueError) as exc:
                last_err = exc
                target.unlink(missing_ok=True)
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))  # small linear backoff
        # Per-URL failures are logged at DEBUG only — a large scope routinely has
        # hundreds of dead JS URLs (e.g. 404 gtm.js from crawler over-reporting),
        # and one WARNING each floods the log. The worker logs a per-batch
        # summary instead.
        logger.debug("JS download failed: %s (%s)", url, last_err)
        return None

    def _stream_to_file(self, url: str, target: Path) -> None:
        """Stream *url* to *target*, capping at :data:`_MAX_FILE_BYTES`."""
        request = Request(url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=self.timeout) as resp, target.open("wb") as fh:
            written = 0
            while True:
                chunk = resp.read(_READ_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > _MAX_FILE_BYTES:
                    fh.write(chunk[: _MAX_FILE_BYTES - (written - len(chunk))])
                    break
                fh.write(chunk)

    @staticmethod
    def _safe_filename(url: str) -> str:
        """A collision-free ``.js`` filename derived from the URL hash.

        Using a hash (rather than the URL's basename) avoids path traversal,
        filesystem-illegal characters, and name collisions between different
        hosts that share a basename like ``main.js``.
        """
        digest = hashlib.sha1(url.encode("utf-8", errors="replace")).hexdigest()
        return f"{digest}.js"

    # ------------------------------------------------------------------
    # Cleanup — MUST run even on failure
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Remove the temp directory and everything in it. Idempotent."""
        try:
            shutil.rmtree(self._dir, ignore_errors=True)
        except Exception as exc:  # never raise from cleanup
            logger.warning("Failed to clean up JS processing dir %s: %s", self._dir, exc)
