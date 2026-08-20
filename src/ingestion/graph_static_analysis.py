"""Modest static analysis for the L3 graph: catches drift, never a substitute for the manifest.

Scope is deliberately narrow per CLAUDE.md section 5: package deps from
requirements.txt/pyproject.toml/package.json, FastAPI route decorators, and
hardcoded URLs. No full call-graph analysis.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass

_REQUIREMENT_RE = re.compile(r"^([A-Za-z0-9_.\-]+)\s*([=<>!~]{1,2}=?[^\s;#]*)?")
_ROUTE_DECORATOR_RE = re.compile(r"@\s*\w+\.(get|post|put|delete|patch)\s*\(\s*[\"']([^\"']+)[\"']")
_URL_RE = re.compile(r"https?://[^\s\"'()\[\]<>]+")


@dataclass(frozen=True)
class PackageDep:
    name: str
    version_constraint: str | None


@dataclass(frozen=True)
class ExposedRoute:
    method: str
    path: str


def parse_requirements_txt(content: str) -> list[PackageDep]:
    deps = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        match = _REQUIREMENT_RE.match(line)
        if match:
            deps.append(PackageDep(name=match.group(1), version_constraint=match.group(2)))
    return deps


def parse_pyproject_toml(content: str) -> list[PackageDep]:
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return []

    deps = []
    for entry in data.get("project", {}).get("dependencies", []) or []:
        match = _REQUIREMENT_RE.match(entry.strip())
        if match:
            deps.append(PackageDep(name=match.group(1), version_constraint=match.group(2)))

    poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {}) or {}
    for name, spec in poetry_deps.items():
        if name.lower() == "python":
            continue
        version: str | None = None
        if isinstance(spec, str):
            version = spec
        elif isinstance(spec, dict) and isinstance(spec.get("version"), str):
            version = spec["version"]
        deps.append(PackageDep(name=name, version_constraint=version))

    return deps


def parse_package_json(content: str) -> list[PackageDep]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []

    deps = []
    for section in ("dependencies", "devDependencies"):
        for name, version in (data.get(section) or {}).items():
            deps.append(PackageDep(name=name, version_constraint=version))
    return deps


def find_fastapi_routes(content: str) -> list[ExposedRoute]:
    return [
        ExposedRoute(method=method.upper(), path=path)
        for method, path in _ROUTE_DECORATOR_RE.findall(content)
    ]


def find_hardcoded_urls(content: str) -> list[str]:
    return sorted(set(_URL_RE.findall(content)))
