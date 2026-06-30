"""Storage service — UUID-based layout (Phase 4).

New canonical layout::

    storage/
    ├── programs/
    │   └── {program_id}/
    │       └── scopes/
    │           └── {scope_id}/
    │               ├── subdomains/
    │               │   ├── raw/
    │               │   └── processed/
    │               ├── dns/
    │               │   ├── raw/
    │               │   └── processed/
    │               ├── http/
    │               │   ├── raw/
    │               │   └── processed/
    │               ├── diff/
    │               ├── logs/
    │               ├── screenshots/
    │               └── reports/
    ├── exports/
    ├── archives/
    ├── temp/
    └── screenshots/

Legacy layout (programs named by slug, scopes named by target) is kept
accessible via read-only fallback so old scan artifacts are not lost.
The migrate_legacy() method moves old data into the new tree.
"""

from __future__ import annotations

import logging
import re
import shutil
import uuid as _uuid_module
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

_REPO_ROOT: Path = Path(__file__).resolve().parents[2]

STORAGE_ROOT: Path = _REPO_ROOT / "storage"
PROGRAMS_DIR: Path = STORAGE_ROOT / "programs"   # new UUID-keyed tree
PROJECTS_DIR: Path = STORAGE_ROOT / "projects"   # legacy human-readable tree
EXPORTS_DIR: Path = STORAGE_ROOT / "exports"
ARCHIVES_DIR: Path = STORAGE_ROOT / "archives"
TEMP_DIR: Path = STORAGE_ROOT / "temp"
SCREENSHOTS_DIR: Path = STORAGE_ROOT / "screenshots"

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_PHASES_WITH_SUBDIRS = ("subdomains", "dns", "http", "live", "urls", "js", "nuclei")
_PHASES_FLAT = ("diff", "logs", "screenshots", "reports")


def _is_uuid(name: str) -> bool:
    return bool(_UUID_RE.match(name))


def normalize_scope_path(scope_target: str) -> str:
    """Filesystem-safe name from a scope target (legacy helper, kept for compat)."""
    name = scope_target.strip()
    name = name.replace("*.", "wildcard_")
    name = re.sub(r"[^\w.\-]", "_", name)
    return name


class StorageService:
    """UUID-keyed filesystem storage for all recon artifacts.

    Primary path helpers use UUIDs so names can change without breaking paths.
    Legacy helpers that accept program_name / scope_target strings still work
    and are used by the Phase 3 subdomain worker until it is upgraded.
    """

    def __init__(self, root_path: str | Path | None = None) -> None:
        self._root = Path(root_path) if root_path is not None else STORAGE_ROOT
        self._ensure_top_level_dirs()

    # ------------------------------------------------------------------
    # UUID-keyed primary API
    # ------------------------------------------------------------------

    def get_program_path_by_id(self, program_id: _uuid_module.UUID | str) -> Path:
        return self._root / "programs" / str(program_id)

    def get_scope_path_by_id(
        self,
        program_id: _uuid_module.UUID | str,
        scope_id: _uuid_module.UUID | str,
    ) -> Path:
        return self.get_program_path_by_id(program_id) / "scopes" / str(scope_id)

    def get_phase_path_by_id(
        self,
        program_id: _uuid_module.UUID | str,
        scope_id: _uuid_module.UUID | str,
        phase: str,
    ) -> Path:
        path = self.get_scope_path_by_id(program_id, scope_id) / phase
        self._mkdir(path)
        return path

    def get_raw_path_by_id(
        self,
        program_id: _uuid_module.UUID | str,
        scope_id: _uuid_module.UUID | str,
        phase: str,
    ) -> Path:
        return self._scope_subdir_by_id(program_id, scope_id, phase, "raw")

    def get_processed_path_by_id(
        self,
        program_id: _uuid_module.UUID | str,
        scope_id: _uuid_module.UUID | str,
        phase: str,
    ) -> Path:
        return self._scope_subdir_by_id(program_id, scope_id, phase, "processed")

    def get_diff_path_by_id(
        self,
        program_id: _uuid_module.UUID | str,
        scope_id: _uuid_module.UUID | str,
    ) -> Path:
        return self.get_phase_path_by_id(program_id, scope_id, "diff")

    def get_logs_path_by_id(
        self,
        program_id: _uuid_module.UUID | str,
        scope_id: _uuid_module.UUID | str,
    ) -> Path:
        return self.get_phase_path_by_id(program_id, scope_id, "logs")

    def get_reports_path_by_id(
        self,
        program_id: _uuid_module.UUID | str,
        scope_id: _uuid_module.UUID | str,
    ) -> Path:
        return self.get_phase_path_by_id(program_id, scope_id, "reports")

    def init_scope_directories_by_id(
        self,
        program_id: _uuid_module.UUID | str,
        scope_id: _uuid_module.UUID | str,
    ) -> Path:
        """Create the full scope directory tree using UUIDs. Idempotent."""
        scope_path = self.get_scope_path_by_id(program_id, scope_id)
        self._mkdir(scope_path)
        for phase in _PHASES_WITH_SUBDIRS:
            self._scope_subdir_by_id(program_id, scope_id, phase, "raw")
            self._scope_subdir_by_id(program_id, scope_id, phase, "processed")
        for phase in _PHASES_FLAT:
            self.get_phase_path_by_id(program_id, scope_id, phase)
        logger.info("Initialised UUID scope directories: %s", scope_path)
        return scope_path

    # ------------------------------------------------------------------
    # Legacy name-based API (kept for backward compat with Phase-3 worker)
    # ------------------------------------------------------------------

    def get_storage_root(self) -> Path:
        return self._root

    def get_program_path(self, program_name: str) -> Path:
        return self._root / "projects" / self._safe_name(program_name)

    def get_scope_path(self, program_name: str, scope_target: str) -> Path:
        return self.get_program_path(program_name) / "scopes" / normalize_scope_path(scope_target)

    def get_phase_path(self, program_name: str, scope_target: str, phase: str) -> Path:
        path = self.get_scope_path(program_name, scope_target) / phase
        self._mkdir(path)
        return path

    def get_raw_path(self, program_name: str, scope_target: str, phase: str = "general") -> Path:
        return self._scope_subdir(program_name, scope_target, phase, "raw")

    def get_processed_path(self, program_name: str, scope_target: str, phase: str = "general") -> Path:
        return self._scope_subdir(program_name, scope_target, phase, "processed")

    def get_diff_path(self, program_name: str, scope_target: str) -> Path:
        return self.get_phase_path(program_name, scope_target, "diff")

    def get_logs_path(self, program_name: str, scope_target: str) -> Path:
        return self.get_phase_path(program_name, scope_target, "logs")

    def get_screenshots_path(self, program_name: str, scope_target: str) -> Path:
        return self.get_phase_path(program_name, scope_target, "screenshots")

    def get_nuclei_path(self, program_name: str, scope_target: str) -> Path:
        return self.get_phase_path(program_name, scope_target, "nuclei")

    def get_reports_path(self, program_name: str, scope_target: str) -> Path:
        return self.get_phase_path(program_name, scope_target, "reports")

    def get_metadata_path(self, program_name: str) -> Path:
        path = self.get_program_path(program_name) / "metadata"
        self._mkdir(path)
        return path

    def init_scope_directories(self, program_name: str, scope_target: str) -> Path:
        """Legacy: create directory tree using human-readable names."""
        scope_path = self.get_scope_path(program_name, scope_target)
        self._mkdir(scope_path)
        for phase in ("subdomains", "live", "urls", "js", "nuclei"):
            self.get_raw_path(program_name, scope_target, phase)
            self.get_processed_path(program_name, scope_target, phase)
        for phase in ("diff", "logs", "screenshots", "reports"):
            self.get_phase_path(program_name, scope_target, phase)
        logger.info("Initialised scope directories (legacy): %s", scope_path)
        return scope_path

    # ------------------------------------------------------------------
    # Artifact helpers (shared)
    # ------------------------------------------------------------------

    def save_lines_artifact(
        self,
        directory: Path,
        artifact_name: str,
        lines: Iterable[str],
    ) -> Path:
        """Write line-oriented artifacts without building one giant string."""
        target = directory / artifact_name
        with target.open("w", encoding="utf-8") as fh:
            first = True
            for line in lines:
                if not first:
                    fh.write("\n")
                fh.write(line)
                first = False
        logger.debug("Wrote line artifact: %s", target)
        return target

    def save_raw_artifact(
        self,
        program_name: str,
        scope_target: str,
        artifact_name: str,
        content: str,
        phase: str = "general",
    ) -> Path:
        target = self.get_raw_path(program_name, scope_target, phase) / artifact_name
        target.write_text(content, encoding="utf-8")
        return target

    def save_processed_artifact(
        self,
        program_name: str,
        scope_target: str,
        artifact_name: str,
        content: str,
        phase: str = "general",
    ) -> Path:
        target = self.get_processed_path(program_name, scope_target, phase) / artifact_name
        target.write_text(content, encoding="utf-8")
        return target

    def save_diff_artifact(
        self,
        program_name: str,
        scope_target: str,
        artifact_name: str,
        content: str,
    ) -> Path:
        target = self.get_diff_path(program_name, scope_target) / artifact_name
        target.write_text(content, encoding="utf-8")
        return target

    # ------------------------------------------------------------------
    # Migration: legacy name-based → UUID-based
    # ------------------------------------------------------------------

    def migrate_legacy(
        self,
        program_id: _uuid_module.UUID | str,
        scope_id: _uuid_module.UUID | str,
        program_name: str,
        scope_target: str,
    ) -> bool:
        """Move artifacts from the legacy name-based tree to the UUID tree.

        Safe to call multiple times — skips if source does not exist.
        Returns True when a migration was performed, False when nothing to do.
        """
        src = self.get_scope_path(program_name, scope_target)
        if not src.exists():
            return False

        dst = self.get_scope_path_by_id(program_id, scope_id)
        if dst.exists():
            logger.info(
                "UUID scope directory already exists (%s) — skipping legacy migration", dst
            )
            return False

        self._mkdir(dst.parent)
        shutil.copytree(str(src), str(dst))
        logger.info("Migrated legacy scope storage: %s -> %s", src, dst)
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_top_level_dirs(self) -> None:
        for sub in ("programs", "projects", "exports", "archives", "temp", "screenshots"):
            self._mkdir(self._root / sub)

    def _scope_subdir_by_id(
        self,
        program_id: _uuid_module.UUID | str,
        scope_id: _uuid_module.UUID | str,
        phase: str,
        subdir: str,
    ) -> Path:
        path = self.get_phase_path_by_id(program_id, scope_id, phase) / subdir
        self._mkdir(path)
        return path

    def _scope_subdir(
        self, program_name: str, scope_target: str, phase: str, subdir: str
    ) -> Path:
        path = self.get_phase_path(program_name, scope_target, phase) / subdir
        self._mkdir(path)
        return path

    def _mkdir(self, path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        logger.debug("Directory ensured: %s", path)
        return path

    @staticmethod
    def _safe_name(name: str) -> str:
        return name.strip().lower().replace(" ", "_")
