"""Tests for outbound webhook HMAC-SHA256 signing."""
from __future__ import annotations

import hashlib
import hmac



def compute_expected_signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestWebhookSigning:
    def test_sign_body_produces_valid_hmac(self):
        from server.workflow_engine import _sign_request_headers
        body = b'{"event": "test"}'
        secret = "my-webhook-secret"
        headers = _sign_request_headers(secret, body)
        assert "X-Noba-Signature" in headers
        expected = compute_expected_signature(secret, body)
        assert headers["X-Noba-Signature"] == expected

    def test_sign_empty_secret_returns_no_header(self):
        from server.workflow_engine import _sign_request_headers
        headers = _sign_request_headers("", b"body")
        assert headers == {}

    def test_sign_none_secret_returns_no_header(self):
        from server.workflow_engine import _sign_request_headers
        headers = _sign_request_headers(None, b"body")
        assert headers == {}

    def test_signature_changes_with_body(self):
        from server.workflow_engine import _sign_request_headers
        h1 = _sign_request_headers("secret", b"body1")
        h2 = _sign_request_headers("secret", b"body2")
        assert h1["X-Noba-Signature"] != h2["X-Noba-Signature"]

    def test_signature_changes_with_secret(self):
        from server.workflow_engine import _sign_request_headers
        h1 = _sign_request_headers("secret1", b"body")
        h2 = _sign_request_headers("secret2", b"body")
        assert h1["X-Noba-Signature"] != h2["X-Noba-Signature"]
