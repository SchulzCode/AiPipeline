from aipipe.control.security import verify_github_signature
import hashlib, hmac


def test_webhook_signature_verification():
    body = b'{"hello":"world"}'
    secret = "test-secret"
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_github_signature(secret, body, signature)
    assert not verify_github_signature(secret, body + b"!", signature)
    assert not verify_github_signature(secret, body, None)
