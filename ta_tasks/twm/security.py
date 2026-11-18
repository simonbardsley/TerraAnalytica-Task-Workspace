"""Sanitisation helpers (spec s17): no credentials in workspace state or AI context."""
from __future__ import annotations

import hashlib
import re
from typing import Any

_SECRET_KEY_RE = re.compile(
    r"(password|passwd|pwd|secret|token|api[_-]?key|authcfg|credential|bearer)", re.I
)
_KV_RE = re.compile(
    r"""(?i)(?<![A-Za-z_])(user(?:name)?|password|passwd|pwd|authcfg|token|"""
    r"""api[_-]?key|access[_-]?token|secret|key)\s*=\s*('[^']*'|"[^"]*"|[^\s&;]+)"""
)
_USERINFO_RE = re.compile(r"(?i)(://)[^/@\s:]+:[^/@\s]+@")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S
)


def sanitise_uri(uri: str) -> str:
    """Strip credentials from a data-source URI / connection string."""
    out = _USERINFO_RE.sub(r"\1***@", uri or "")
    return _KV_RE.sub(lambda m: f"{m.group(1)}=***", out)


def redact_text(text: str) -> str:
    """Redact common inline credentials before text reaches logs or audit data."""
    out = sanitise_uri(text or "")
    out = _BEARER_RE.sub("Bearer ***", out)
    return _PRIVATE_KEY_RE.sub("[REDACTED PRIVATE KEY]", out)


def hash_source(uri: str) -> str:
    """Stable short hash of the *sanitised* URI, safe to store."""
    return hashlib.sha256(sanitise_uri(uri).encode("utf-8")).hexdigest()[:16]


def scrub_secrets(obj: Any) -> Any:
    """Recursively drop dict keys that look like credentials."""
    if isinstance(obj, dict):
        return {k: scrub_secrets(v) for k, v in obj.items() if not _SECRET_KEY_RE.search(str(k))}
    if isinstance(obj, (list, tuple)):
        return [scrub_secrets(v) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


# ----------------------------------------------------------- secret detection
_SECRET_RULES = {
    "credential assignment": re.compile(
        r"""(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|token|authcfg)["']?\s*[=:]\s*["']?[^\s"',;}]{4,}"""
    ),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "URI with embedded credentials": re.compile(r"://[^/@\s:]+:[^/@\s]+@"),
}


def find_secrets(text: str) -> list[str]:
    """Names of secret-looking patterns present in ``text`` (never returns the match)."""
    return [name for name, rx in _SECRET_RULES.items() if rx.search(text)]
