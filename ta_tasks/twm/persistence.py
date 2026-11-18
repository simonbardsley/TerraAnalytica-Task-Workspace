"""Persistence abstraction + JSON backend (M0).

* Atomic writes (temp file + fsync + replace).
* Last-known-good: the previous valid file is kept as ``<name>.bak``.
* Corrupt primary falls back to the backup and flags ``recovered``.
* Schema newer than supported opens read-only and never rewrites the file.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .logging_utils import get_logger
from .migration import migrate
from .schemas import Project, SchemaError, SchemaTooNew

log = get_logger("persistence")


class ReadOnlyError(RuntimeError):
    """Raised on any attempt to write a read-only (newer-schema) project."""


class StoreCorruptError(RuntimeError):
    """Primary and backup are both unreadable."""


@dataclass
class LoadResult:
    project: Project
    recovered: bool = False
    read_only: bool = False
    warnings: list[str] = field(default_factory=list)


class ProjectStore(Protocol):
    def exists(self) -> bool: ...
    def load(self) -> LoadResult: ...
    def save(self, project: Project, read_only: bool = False, reason: str = "") -> None: ...


class JsonProjectStore:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")

    def exists(self) -> bool:
        return self.path.exists() or self.backup_path.exists()

    # -- read
    def _read(self, p: Path) -> LoadResult:
        raw = json.loads(p.read_text(encoding="utf-8"))
        try:
            return LoadResult(Project.from_dict(migrate(raw)))
        except SchemaTooNew as exc:
            project = Project.from_dict(raw, allow_newer=True)
            return LoadResult(project, read_only=True,
                              warnings=[f"{exc}; opened read-only, file preserved."])

    def load(self) -> LoadResult:
        errors: list[str] = []
        for candidate, is_backup in ((self.path, False), (self.backup_path, True)):
            if not candidate.exists():
                continue
            try:
                res = self._read(candidate)
                if is_backup:
                    res.recovered = True
                    res.warnings.insert(0, f"Recovered from last known good ({candidate.name}): "
                                           + "; ".join(errors))
                    log.warning(res.warnings[0])
                return res
            except (json.JSONDecodeError, SchemaError, OSError, UnicodeDecodeError) as exc:
                errors.append(f"{candidate.name}: {exc}")
        if not errors:
            raise FileNotFoundError(self.path)
        raise StoreCorruptError("; ".join(errors))

    # -- write
    def _valid(self, p: Path) -> bool:
        try:
            Project.from_dict(migrate(json.loads(p.read_text(encoding="utf-8"))))
            return True
        except Exception:  # noqa: BLE001
            return False

    def save(self, project: Project, read_only: bool = False, reason: str = "") -> None:
        if read_only:
            raise ReadOnlyError("Project was opened read-only (newer schema); not saving.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = json.dumps(project.to_dict(), indent=2, ensure_ascii=False, sort_keys=False)
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        if self.path.exists() and self._valid(self.path):
            shutil.copy2(self.path, self.backup_path)  # only valid files become last-known-good
        os.replace(tmp, self.path)
