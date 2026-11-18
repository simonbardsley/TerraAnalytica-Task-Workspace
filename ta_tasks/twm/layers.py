"""Semantic layer roles and safe layer-reference resolution (M7; spec s7.3 and s18).

Resolution order for a stored ``LayerRef`` (first decisive step wins):
  1. layer id            -> RESOLVED, high confidence (flags *drift* if name/source changed since binding)
  2. provider + source   -> RESOLVED, high confidence if exactly one layer matches
     hash                   (ties are narrowed by exact name; otherwise AMBIGUOUS)
  3. provider + name     -> RESOLVED, **medium** confidence if exactly one layer matches
                            (never auto-persisted; the user is asked to confirm)
  4. nothing             -> UNRESOLVED, binding preserved, near-miss suggestions listed

Safety rules: never pick among several candidates; never accept a layer whose provider differs from the
bound one; never store raw source URIs (only a hash of the credential-stripped URI).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from .schemas import LayerRef, Task
from .security import hash_source

STANDARD_ROLES = (
    "multispectral_imagery", "reference_data", "training_labels", "analysis_output",
    "paddock_boundaries", "vegetation_indices", "paddock_statistics",
)
ASSOCIATION_KINDS = ("notebook", "plot", "map", "model", "workflow")
_ROLE_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_ITEM_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,256}$")


def validate_role_name(role: str) -> str:
    if not isinstance(role, str) or not _ROLE_RE.match(role):
        raise ValueError(f"Invalid role name {role!r}: use lower_snake_case, 2-64 characters, starting with a letter")
    return role


def validate_association(kind: str, item_id: str) -> tuple[str, str]:
    if kind not in ASSOCIATION_KINDS:
        raise ValueError(f"Unknown association kind {kind!r}; expected one of {', '.join(ASSOCIATION_KINDS)}")
    if not isinstance(item_id, str) or not _ITEM_RE.match(item_id.strip()):
        raise ValueError("Association id must be 1-256 printable characters")
    return kind, item_id.strip()


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class LayerInfo:
    """What TWM needs to know about a live layer. Contains NO raw source string."""

    layer_id: str
    name: str
    provider: str = ""
    source_hash: str = ""

    @classmethod
    def from_raw(cls, layer_id: str, name: str, provider: str, raw_source: str) -> LayerInfo:
        return cls(str(layer_id), str(name), str(provider or ""), hash_source(str(raw_source or "")))

    def to_ref(self, role: str) -> LayerRef:
        return LayerRef(layer_id=self.layer_id, provider=self.provider, source_hash=self.source_hash,
                        name=self.name, role=role)


class LayerCatalogue(Protocol):
    def list_layers(self) -> list[LayerInfo]: ...


@dataclass
class Resolution:
    ref: LayerRef
    status: ResolutionStatus
    method: str = ""                 # id | source | source+name | name | ""
    confidence: str = ""             # high | medium | ""
    layer: LayerInfo | None = None
    candidates: list[LayerInfo] = field(default_factory=list)   # ambiguous matches or unresolved suggestions
    drift: bool = False              # id matched but name AND source differ from when bound
    healed: LayerRef | None = None   # refreshed ref, only set for high-confidence non-id matches

    @property
    def needs_confirmation(self) -> bool:
        return self.status == ResolutionStatus.RESOLVED and self.confidence == "medium"


def _norm_pool(ref: LayerRef, layers: list[LayerInfo]) -> list[LayerInfo]:
    if not ref.provider:
        return list(layers)
    return [lyr for lyr in layers if not lyr.provider or lyr.provider == ref.provider]


def resolve_ref(ref: LayerRef, layers: list[LayerInfo]) -> Resolution:
    by_id = {lyr.layer_id: lyr for lyr in layers}
    hit = by_id.get(ref.layer_id) if ref.layer_id else None
    if hit is not None:
        drift = bool(ref.source_hash and ref.name and hit.source_hash != ref.source_hash and hit.name != ref.name)
        return Resolution(ref, ResolutionStatus.RESOLVED, "id", "high", hit, [hit], drift=drift)

    pool = _norm_pool(ref, layers)

    if ref.source_hash:
        matches = [lyr for lyr in pool if lyr.source_hash == ref.source_hash]
        if len(matches) == 1:
            return _resolved_by(ref, matches[0], "source")
        if len(matches) > 1:
            narrowed = [lyr for lyr in matches if ref.name and lyr.name == ref.name]
            if len(narrowed) == 1:
                return _resolved_by(ref, narrowed[0], "source+name")
            return Resolution(ref, ResolutionStatus.AMBIGUOUS, candidates=matches)

    if ref.name:
        matches = [lyr for lyr in pool if lyr.name == ref.name]
        if len(matches) == 1:
            return Resolution(ref, ResolutionStatus.RESOLVED, "name", "medium", matches[0], matches)
        if len(matches) > 1:
            return Resolution(ref, ResolutionStatus.AMBIGUOUS, candidates=matches)

    near = [lyr for lyr in pool if ref.name and lyr.name.casefold() == ref.name.casefold()]
    return Resolution(ref, ResolutionStatus.UNRESOLVED, candidates=near)


def _resolved_by(ref: LayerRef, layer: LayerInfo, method: str) -> Resolution:
    healed = LayerRef(layer_id=layer.layer_id, provider=layer.provider or ref.provider,
                      source_hash=layer.source_hash, name=layer.name, role=ref.role, extra=dict(ref.extra))
    return Resolution(ref, ResolutionStatus.RESOLVED, method, "high", layer, [layer], healed=healed)


@dataclass
class RoleResult:
    role: str
    direction: str = ""              # "input" | "output" | "" (bound but undeclared)
    required: bool = False
    resolutions: list[Resolution] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.resolutions:
            return "unbound"
        statuses = {r.status for r in self.resolutions}
        if ResolutionStatus.UNRESOLVED in statuses:
            return "unresolved"
        if ResolutionStatus.AMBIGUOUS in statuses:
            return "ambiguous"
        return "resolved"


@dataclass
class RoleResolutionReport:
    task_id: str
    roles: dict[str, RoleResult] = field(default_factory=dict)

    def statuses(self) -> dict[str, str]:
        return {role: r.status for role, r in self.roles.items()}

    def missing_required_inputs(self) -> list[str]:
        return [role for role, r in self.roles.items()
                if r.direction == "input" and r.required and r.status != "resolved"]

    def healable(self) -> list[tuple[str, LayerRef, LayerRef]]:
        """High-confidence refreshes safe to persist: (role, old_ref, new_ref)."""
        return [(role, res.ref, res.healed) for role, r in self.roles.items()
                for res in r.resolutions if res.healed is not None]

    def warnings(self) -> list[str]:
        out: list[str] = []
        for role, r in self.roles.items():
            if r.direction == "input" and r.required and r.status == "unbound":
                out.append(f"Role '{role}': no layer bound")
            for res in r.resolutions:
                nm = res.ref.name or res.ref.layer_id
                if res.status == ResolutionStatus.UNRESOLVED:
                    hint = (f" (similar: {', '.join(c.name for c in res.candidates)})" if res.candidates else "")
                    out.append(f"Role '{role}': layer '{nm}' not found{hint}")
                elif res.status == ResolutionStatus.AMBIGUOUS:
                    names = ", ".join(c.name for c in res.candidates)
                    out.append(f"Role '{role}': '{nm}' matches {len(res.candidates)} layers ({names}); choose one")
                elif res.needs_confirmation:
                    out.append(f"Role '{role}': '{nm}' matched by name only; confirm the binding")
                elif res.drift:
                    out.append(f"Role '{role}': layer '{nm}' has a different name and source than when bound")
        return out


def resolve_task_roles(task: Task, layers: list[LayerInfo]) -> RoleResolutionReport:
    report = RoleResolutionReport(task.id)
    for direction, specs in (("input", task.inputs), ("output", task.outputs)):
        for spec in specs:
            report.roles[spec.role] = RoleResult(spec.role, direction, spec.required and direction == "input")
    for role in task.role_bindings:
        report.roles.setdefault(role, RoleResult(role))
    for role, refs in task.role_bindings.items():
        report.roles[role].resolutions = [resolve_ref(ref, layers) for ref in refs]
    return report
