import base64
import logging
from typing import Any, Dict, Optional
import atexit
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Random import get_random_bytes

from contextlib import suppress
from utils.azure_secrets import get_secret_sync
from core.constants import ENV

_old_factory = logging.getLogRecordFactory()


def strip_source_log_record_factory(*args, **kwargs):
    record = _old_factory(*args, **kwargs)
    record.pathname = None
    record.funcName = None
    record.lineno = 0
    return record


logging.setLogRecordFactory(strip_source_log_record_factory)

_logger = None
_logger_provider = None


def init_ai_logger():
    global _logger
    if _logger:
        return _logger

    return None


def derive_key(master_secret: bytes, salt: bytes) -> bytes:
    return PBKDF2(
        password=master_secret,
        salt=salt,
        dkLen=32,  # AES‑256
        count=200_000,  # strong PBKDF2 iteration count
        hmac_hash_module=SHA256,
    )


def encrypt_pii(plain_text: str, master_secret: bytes) -> str:
    if master_secret is None:
        return plain_text  # or return "" or something
    if not isinstance(master_secret, (bytes, bytearray)):
        raise TypeError("master_secret must be bytes")

    salt = get_random_bytes(16)
    key = derive_key(master_secret, salt)

    nonce = get_random_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)

    ciphertext, tag = cipher.encrypt_and_digest(plain_text.encode("utf-8"))

    encrypted_payload = b"".join([salt, nonce, tag, ciphertext])

    return base64.b64encode(encrypted_payload).decode("utf-8")


def log_ai(
    message: str,
    level: int = logging.INFO,
    custom_dimensions: Optional[Dict[str, Any]] = None,
):
    if not _logger:
        return

    _logger.log(level, message, extra={"custom_dimensions": custom_dimensions or {}})


master_secret = get_secret_sync("master-secret")
master_secret_bytes = master_secret.encode("utf-8") if master_secret else None


def log_record(staff_id, request_params, endpoint, request_type, status_code, response):
    log_ai(
        message=response,
        custom_dimensions={
            "StaffID": encrypt_pii(staff_id, master_secret_bytes) if staff_id else "",
            "RequestParams": request_params,
            "EndPoint": endpoint,
            "RequestType": (
                request_type.upper() if isinstance(request_type, str) else ""
            ),
            "StatusCode": status_code,
            "ENV":ENV
        },
    )


def shutdown_ai_logger():
    global _logger, _logger_provider
    if _logger:
        for handler in _logger.handlers:
            handler.flush()
            handler.close()
        _logger = None
    if _logger_provider:
        with suppress(Exception):
            _logger_provider.shutdown()
        _logger_provider = None
        with suppress(Exception):
            _logger_provider.flush()
    with suppress(Exception):
        logging.shutdown()


with suppress(Exception):
    atexit.unregister(logging.shutdown)