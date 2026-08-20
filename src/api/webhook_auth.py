"""HMAC verification for GitHub webhooks - X-Hub-Signature-256, not Bearer auth."""

from __future__ import annotations

import hashlib
import hmac


def verify_github_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    if not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
