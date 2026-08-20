"""Secret scanning: run before anything is stored or embedded. Never carries the matched value."""

from __future__ import annotations

import fnmatch
import tempfile
from dataclasses import dataclass
from pathlib import Path

from detect_secrets.core.secrets_collection import SecretsCollection
from detect_secrets.settings import default_settings

EXCLUDED_PATH_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa*",
    "credentials",
    ".aws/*",
    "terraform.tfstate*",
]


@dataclass(frozen=True)
class SecretFinding:
    rule_id: str


def is_excluded_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(name, p) for p in EXCLUDED_PATH_PATTERNS)


def scan_for_secrets(content: str, suffix: str = ".txt") -> list[SecretFinding]:
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        f.write(content)
        path = Path(f.name)

    try:
        collection = SecretsCollection()
        with default_settings():
            collection.scan_file(str(path))
        return [
            SecretFinding(rule_id=finding.type)
            for findings in collection.data.values()
            for finding in findings
        ]
    finally:
        path.unlink(missing_ok=True)
