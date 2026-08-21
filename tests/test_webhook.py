import hashlib
import hmac

from main import _verify_signature
from shipwright import config


def test_hmac_accepts_apple_format_and_rejects_forgery(monkeypatch):
    monkeypatch.setattr(config, "ASC_WEBHOOK_SECRET", "test-secret")
    body = b'{"data":{"type":"buildUploadStateUpdated"}}'
    good = "hmacsha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    assert _verify_signature(body, good)
    assert not _verify_signature(body, "hmacsha256=" + "0" * 64)
    assert not _verify_signature(body, None)
    assert not _verify_signature(body + b" ", good)  # any byte change breaks it
