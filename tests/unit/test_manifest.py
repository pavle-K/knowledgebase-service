import pytest

from src.ingestion.manifest import ManifestError, parse_manifest

VALID_MANIFEST = """
name: flight-customer-data-api
description: Universal customer identity and audit logging service.
technologies: [python, fastapi, postgres, aws-lambda, terraform]
exposes:
  - kind: http_endpoint
    identifier: "GET /users/{id}/flight-history"
    contract: { returns: "list[Booking]" }
  - kind: http_endpoint
    identifier: "POST /users/{id}/gdpr-anonymize"
  - kind: db_table
    identifier: "gdpr_consent_logs"
consumes:
  - kind: http_call
    provider: portfolio-knowledge-api
    identifier: "POST /v1/query"
"""


def test_parses_valid_manifest() -> None:
    manifest = parse_manifest(VALID_MANIFEST)

    assert manifest.name == "flight-customer-data-api"
    assert manifest.technologies == ["python", "fastapi", "postgres", "aws-lambda", "terraform"]
    assert len(manifest.exposes) == 3
    assert manifest.exposes[0].kind == "http_endpoint"
    assert manifest.exposes[0].identifier == "GET /users/{id}/flight-history"
    assert manifest.exposes[0].contract == {"returns": "list[Booking]"}
    assert len(manifest.consumes) == 1
    assert manifest.consumes[0].provider == "portfolio-knowledge-api"
    assert manifest.consumes[0].identifier == "POST /v1/query"


def test_minimal_manifest_with_only_name() -> None:
    manifest = parse_manifest("name: bare-project\n")
    assert manifest.name == "bare-project"
    assert manifest.exposes == []
    assert manifest.consumes == []


def test_malformed_yaml_raises_clear_error_not_crash() -> None:
    with pytest.raises(ManifestError):
        parse_manifest("name: broken\n  bad indent: [unterminated\n")


def test_missing_name_field_raises() -> None:
    with pytest.raises(ManifestError):
        parse_manifest("description: no name here\n")


def test_non_mapping_top_level_raises() -> None:
    with pytest.raises(ManifestError):
        parse_manifest("- just\n- a\n- list\n")


def test_exposes_entry_missing_required_field_raises() -> None:
    content = "name: broken-exposes\nexposes:\n  - kind: http_endpoint\n"
    with pytest.raises(ManifestError):
        parse_manifest(content)
