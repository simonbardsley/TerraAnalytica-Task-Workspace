"""Git-backed project store: every change is a commit (local repo only).

Security / integrity choices
* Uses the ``git`` CLI via argument lists - never a shell - so no injection.
* Hooks are disabled (``core.hooksPath`` -> null device + ``--no-verify``): a plugin
  must not execute arbitrary scripts from a project folder.
* No remotes are ever configured and nothing is pushed. Off-machine backup is an
  explicit user/organisation decision.
* History is append-only from TWM's point of view: rollback = a NEW commit that
  restores an older version. TWM never rewrites, amends or force-anything.
* Secrets are refused *before* they reach history (history is hard to purge).
* Commit subjects are sanitised (single line, length-capped); the acting OS user
  and audit-chain head go in trailers.
* Commits may be signed (``sign=True``) if the user has configured signing.
"""
from __future__ import annotations

import json
import os
import re
import shutil
# Reviewed local Git runner import. See _run and SECURITY.md.
import subprocess  # nosec B404
from dataclasses import dataclass, field
from pathlib import Path

from .audit import AuditLog, current_actor
from .events import EventBus
from .logging_utils import get_logger
from .migration import migrate
from .persistence import JsonProjectStore, LoadResult, ReadOnlyError, StoreCorruptError
from .registry import TaskRegistry
from .schemas import Project, SchemaError
from .security import find_secrets

log = get_logger("gitstore")

PROJECT_FILE = "project.json"
AUDIT_FILE = "audit.jsonl"
_HASH_RE = re.compile(r"^[0-9a-f]{7,40}$")
_GIT_TIMEOUT = 30


class GitUnavailableError(RuntimeError):
    """git executable not found or repository unusable."""


class SecretDetectedError(ValueError):
    """Refused to persist data that looks like a credential."""


class GitCommandError(RuntimeError):
    pass


@dataclass
class CommitInfo:
    hash: str
    date: str
    subject: str
    actor: str = ""


@dataclass
class VerifyReport:
    ok: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _clean_subject(text: str, limit: int = 200) -> str:
    one_line = " ".join((text or "update").split())
    return one_line[:limit] or "update"


class GitProjectStore:
    def __init__(self, directory: str | os.PathLike, sign: bool = False,
                 actor: str | None = None, git_exe: str | None = None):
        self.dir = Path(directory)
        self.sign = sign
        self.actor = actor or current_actor()
        self.git = git_exe or shutil.which("git")
        if not self.git:
            raise GitUnavailableError("git executable not found on PATH")
        self._json = JsonProjectStore(self.dir / PROJECT_FILE)
        self.audit = AuditLog(self.dir / AUDIT_FILE, actor=self.actor)

    # ------------------------------------------------------------------ git
    def _run(self, *args: str, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess:
        cmd = [self.git, "-c", f"core.hooksPath={os.devnull}", "-c", "core.quotepath=off",
               "-c", "commit.gpgsign=" + ("true" if self.sign else "false"),
               "-c", "user.name=TA Tasks", "-c", "user.email=ta-tasks@localhost", *args]
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
        try:
            # Reviewed B603: the executable is resolved by shutil.which or explicitly
            # supplied by the caller. Arguments are separate, shell=False, hooks are
            # disabled, and commit IDs are validated before reaching this call.
            proc = subprocess.run(  # nosec B603
                cmd, cwd=self.dir, input=input_text, capture_output=True, text=True,
                encoding="utf-8", timeout=_GIT_TIMEOUT, env=env, shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitCommandError(f"git {args[0]} failed: {exc}") from exc
        if check and proc.returncode != 0:
            raise GitCommandError(f"git {args[0]} exited {proc.returncode}: {proc.stderr.strip()[:300]}")
        return proc

    def _ensure_repo(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        if (self.dir / ".git").exists():
            return
        self._run("init", "-q")
        self._run("symbolic-ref", "HEAD", "refs/heads/main")
        (self.dir / ".gitignore").write_text("*.tmp\n*.bak\n*.lock\n", encoding="utf-8")
        log.info("Initialised local git repository at %s (no remotes configured)", self.dir)

    def _has_head(self) -> bool:
        if not (self.dir / ".git").exists():
            return False
        return self._run("rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0

    # ---------------------------------------------------------------- store
    def exists(self) -> bool:
        return (self.dir / PROJECT_FILE).exists() or self._has_head()

    def load(self) -> LoadResult:
        warnings: list[str] = []
        if (self.dir / ".git").exists() and self._has_head():
            dirty = self._run("status", "--porcelain", "--", PROJECT_FILE, check=False).stdout.strip()
            if dirty:
                warnings.append("project.json has changes not recorded in history "
                                "(edited outside TA Tasks, or a previous save was interrupted)")
        try:
            res = self._json.load()
            res.warnings = warnings + res.warnings
            return res
        except (StoreCorruptError, FileNotFoundError) as exc:
            if not self._has_head():
                raise
            proc = self._run("show", f"HEAD:{PROJECT_FILE}")
            try:
                project = Project.from_dict(migrate(json.loads(proc.stdout)))
            except (ValueError, SchemaError) as exc2:
                raise StoreCorruptError(f"working copy and HEAD both unreadable: {exc}; {exc2}") from exc2
            msg = f"project.json unreadable ({exc}); recovered from last committed version"
            log.warning(msg)
            return LoadResult(project, recovered=True, warnings=warnings + [msg])

    def save(self, project: Project, read_only: bool = False, reason: str = "") -> None:
        if read_only:
            raise ReadOnlyError("Project was opened read-only (newer schema); not saving.")
        payload = json.dumps(project.to_dict(), ensure_ascii=False)
        hits = find_secrets(payload)
        if hits:
            raise SecretDetectedError("Refusing to persist: data looks like it contains "
                                      + ", ".join(hits) + ". Remove it and retry.")
        self._ensure_repo()
        self._json.save(project)
        self._commit(reason)

    def _commit(self, reason: str) -> bool:
        paths = [p for p in (PROJECT_FILE, AUDIT_FILE, ".gitignore") if (self.dir / p).exists()]
        self._run("add", "--", *paths)
        if self._run("diff", "--cached", "--quiet", check=False).returncode == 0:
            return False
        msg = (f"{_clean_subject(reason)}\n\nActor: {self.actor}\nAudit-Head: {self.audit.head}\n")
        self._run("commit", "-q", "--no-verify", "--no-gpg-sign" if not self.sign else "-S", "-F", "-",
                  input_text=msg)
        return True

    def flush(self, reason: str = "audit log update") -> bool:
        """Commit any pending project/audit changes (e.g. audit lines since last save)."""
        if not self._has_head():
            return False
        return self._commit(reason)

    # -------------------------------------------------------------- history
    def history(self, limit: int = 50) -> list[CommitInfo]:
        if not self._has_head():
            return []
        out = self._run("log", f"--max-count={int(limit)}", "--format=%H%x1f%aI%x1f%s%x1f%b%x1e").stdout
        commits = []
        for rec in out.split("\x1e"):
            if not rec.strip():
                continue
            h, date, subject, body = (rec.strip("\n").split("\x1f") + ["", "", "", ""])[:4]
            m = re.search(r"^Actor: (.+)$", body, re.M)
            commits.append(CommitInfo(h.strip(), date, subject, m.group(1) if m else ""))
        return commits

    @staticmethod
    def _check_hash(commit: str) -> str:
        if not _HASH_RE.match(commit or ""):
            raise ValueError("Invalid commit id")
        return commit

    def load_at(self, commit: str) -> Project:
        """Read-only view of the project as of ``commit``."""
        c = self._check_hash(commit)
        raw = self._run("show", f"{c}:{PROJECT_FILE}").stdout
        return Project.from_dict(migrate(json.loads(raw)), allow_newer=True)

    def restore_version(self, commit: str) -> Project:
        """Roll back by recording an older version as a NEW commit (history kept)."""
        project = self.load_at(commit)
        self.save(project, reason=f"restore_version {self._check_hash(commit)[:12]}")
        return project

    # --------------------------------------------------------------- verify
    def verify(self) -> VerifyReport:
        rep = VerifyReport(True)
        if (self.dir / ".git").exists():
            fsck = self._run("fsck", "--no-progress", check=False)
            if fsck.returncode != 0:
                rep.problems.append("git fsck reported repository corruption: " + fsck.stderr.strip()[:200])
            if self._has_head():
                for path in (PROJECT_FILE, AUDIT_FILE):
                    if self._run("status", "--porcelain", "--", path, check=False).stdout.strip():
                        rep.warnings.append(f"{path} has uncommitted changes")
            remotes = self._run("remote", check=False).stdout.split()
            if remotes:
                rep.warnings.append("remotes configured: " + ", ".join(remotes)
                                    + " (data may leave this machine)")
        else:
            rep.warnings.append("no repository yet")
        chain = self.audit.verify()
        rep.problems.extend(f"audit: {p}" for p in chain.problems)
        rep.ok = not rep.problems
        return rep


def open_git_registry(directory: str | os.PathLike, project_name: str = "Untitled Project",
                      bus: EventBus | None = None, sign: bool = False) -> tuple[TaskRegistry, GitProjectStore]:
    """Open (or create) a git-backed registry with the audit log wired to the bus."""
    bus = bus or EventBus()
    store = GitProjectStore(directory, sign=sign)
    store.audit.attach(bus)
    reg = TaskRegistry.open_or_create(store, project_name, bus)
    return reg, store
