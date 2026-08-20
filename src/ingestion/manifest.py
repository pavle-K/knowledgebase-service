"""project.yaml parser - the primary, reliable source for the L3 dependency graph.

Static analysis (graph_static_analysis.py) is secondary and only catches drift.
Never fabricate edges: an absent manifest means unknown, not guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml


class ManifestError(Exception):
    """Raised for malformed project.yaml - never crashes the caller."""


@dataclass(frozen=True)
class ExposedInterface:
    kind: str
    identifier: str
    contract: dict[str, object] | None = None


@dataclass(frozen=True)
class Dependency:
    kind: str
    identifier: str
    provider: str | None = None
    version_constraint: str | None = None


@dataclass(frozen=True)
class Manifest:
    name: str
    description: str | None = None
    technologies: list[str] = field(default_factory=list)
    exposes: list[ExposedInterface] = field(default_factory=list)
    consumes: list[Dependency] = field(default_factory=list)


def parse_manifest(content: str) -> Manifest:
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ManifestError(f"malformed project.yaml: {exc}") from exc

    if not isinstance(data, dict):
        raise ManifestError("project.yaml must be a mapping at the top level")
    if "name" not in data or not isinstance(data["name"], str):
        raise ManifestError("project.yaml must have a string 'name' field")

    try:
        exposes = [
            ExposedInterface(
                kind=item["kind"], identifier=item["identifier"], contract=item.get("contract")
            )
            for item in data.get("exposes", []) or []
        ]
        consumes = [
            Dependency(
                kind=item["kind"],
                identifier=item["identifier"],
                provider=item.get("provider"),
                version_constraint=item.get("version_constraint"),
            )
            for item in data.get("consumes", []) or []
        ]
    except (KeyError, TypeError) as exc:
        raise ManifestError(f"malformed project.yaml: {exc}") from exc

    return Manifest(
        name=data["name"],
        description=data.get("description"),
        technologies=list(data.get("technologies", []) or []),
        exposes=exposes,
        consumes=consumes,
    )
