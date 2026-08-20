from src.ingestion.secrets import is_excluded_path, scan_for_secrets

FAKE_AWS_KEY = 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'
FAKE_PRIVATE_KEY = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEpAIBAAKCAQEA1c7+9z5Pad7OejecsQ0bu3aumnAxuNbiZ2m9GVGCPrKlLNzR\n"
    "-----END RSA PRIVATE KEY-----\n"
)
CLEAN_CONTENT = "This is a normal README about a project.\nNo secrets here.\n"


def test_clean_content_has_no_findings() -> None:
    assert scan_for_secrets(CLEAN_CONTENT) == []


def test_aws_key_is_detected() -> None:
    findings = scan_for_secrets(FAKE_AWS_KEY)
    assert len(findings) == 1
    assert findings[0].rule_id == "AWS Access Key"


def test_private_key_is_detected() -> None:
    findings = scan_for_secrets(FAKE_PRIVATE_KEY)
    assert len(findings) == 1
    assert findings[0].rule_id == "Private Key"


def test_finding_never_carries_the_secret_value() -> None:
    findings = scan_for_secrets(FAKE_AWS_KEY)
    finding = findings[0]
    assert vars(finding) == {"rule_id": "AWS Access Key"}
    assert "AKIAIOSFODNN7EXAMPLE" not in repr(finding)
    assert "AKIAIOSFODNN7EXAMPLE" not in str(finding)


def test_excluded_paths() -> None:
    assert is_excluded_path(".env")
    assert is_excluded_path("nested/.env.local")
    assert is_excluded_path("id_rsa")
    assert is_excluded_path("keys/service.pem")
    assert is_excluded_path(".aws/config")
    assert not is_excluded_path("README.md")
    assert not is_excluded_path("docs/architecture.md")
