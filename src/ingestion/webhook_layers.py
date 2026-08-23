"""Path-based layer routing for webhook-driven incremental sync.

A README change touches L1 only; a code file touches L2 + L4; a project.yaml or
package-manifest change touches L3. Deletions are not handled here - out of
scope for now.

L1 scope intentionally matches the seed sync exactly (README.md at root +
docs/*.md) rather than "any markdown file anywhere" - otherwise webhook-driven
sync would pick up files the seed sync never would, causing drift between them.
"""

from __future__ import annotations

from src.ingestion.chunker_code import is_candidate_code_file
from src.ingestion.repo_sync import PACKAGE_MANIFEST_PARSERS


def is_l1_document_path(file_path: str) -> bool:
    return file_path == "README.md" or (file_path.startswith("docs/") and file_path.endswith(".md"))


def affected_layers(file_path: str) -> set[str]:
    basename = file_path.rsplit("/", 1)[-1]
    layers: set[str] = set()

    if basename == "project.yaml" or basename in PACKAGE_MANIFEST_PARSERS:
        layers.add("graph")
    if is_l1_document_path(file_path):
        layers.add("documents")
    if is_candidate_code_file(file_path):
        layers.add("code")
        layers.add("commits")

    return layers
