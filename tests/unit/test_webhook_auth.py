import hashlib
import hmac

from src.api.webhook_auth import verify_github_signature

SECRET = "test-webhook-secret"
PAYLOAD = b'{"action": "opened"}'


def _sign(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def test_valid_signature_is_accepted() -> None:
    signature = _sign(PAYLOAD, SECRET)
    assert verify_github_signature(PAYLOAD, signature, SECRET) is True


def test_wrong_secret_is_rejected() -> None:
    signature = _sign(PAYLOAD, "wrong-secret")
    assert verify_github_signature(PAYLOAD, signature, SECRET) is False


def test_tampered_payload_is_rejected() -> None:
    signature = _sign(PAYLOAD, SECRET)
    tampered = b'{"action": "closed"}'
    assert verify_github_signature(tampered, signature, SECRET) is False


def test_missing_sha256_prefix_is_rejected() -> None:
    raw_hex = hmac.new(SECRET.encode(), PAYLOAD, hashlib.sha256).hexdigest()
    assert verify_github_signature(PAYLOAD, raw_hex, SECRET) is False


def test_empty_signature_is_rejected() -> None:
    assert verify_github_signature(PAYLOAD, "", SECRET) is False
