from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import socket
import uuid
from pathlib import Path
from typing import Any

from django.conf import settings

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when dependency is missing
    InvalidSignature = Exception
    serialization = None
    Ed25519PublicKey = None
    CRYPTOGRAPHY_AVAILABLE = False


TOKEN_PREFIX = "CHL1"


class LicenseError(Exception):
    """Base class for safe, user-facing licensing failures."""


class LicenseConfigurationError(LicenseError):
    pass


class InvalidLicenseError(LicenseError):
    pass


def canonical_json(data: dict[str, Any]) -> bytes:
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except Exception as exc:
        raise InvalidLicenseError("The license contains invalid Base64 data.") from exc


def build_machine_fingerprint() -> str:
    """
    Create a non-secret diagnostic fingerprint.

    It is stored for support/auditing. The actual license binding uses the
    database Installation UUID because it survives normal hardware changes.
    """

    parts = [
        platform.system(),
        platform.release(),
        platform.machine(),
        socket.gethostname(),
        str(uuid.getnode()),
    ]

    for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            value = Path(candidate).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            continue
        if value:
            parts.append(value)
            break

    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _public_key_bytes() -> bytes:
    inline_key = getattr(settings, "LICENSE_PUBLIC_KEY", "") or os.getenv(
        "LICENSE_PUBLIC_KEY",
        "",
    )
    if inline_key:
        return inline_key.replace("\\n", "\n").encode("utf-8")

    configured_path = getattr(settings, "LICENSE_PUBLIC_KEY_FILE", "")
    if configured_path:
        path = Path(configured_path)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise LicenseConfigurationError(
                f"Could not read LICENSE_PUBLIC_KEY_FILE: {path}"
            ) from exc

    raise LicenseConfigurationError(
        "No licensing public key is configured. Set LICENSE_PUBLIC_KEY_FILE "
        "or LICENSE_PUBLIC_KEY."
    )


def load_public_key() -> "Ed25519PublicKey":
    if not CRYPTOGRAPHY_AVAILABLE:
        raise LicenseConfigurationError(
            "The 'cryptography' package is required. "
            "Run: pip install -r requirements-licensing.txt"
        )

    try:
        key = serialization.load_pem_public_key(_public_key_bytes())
    except LicenseConfigurationError:
        raise
    except Exception as exc:
        raise LicenseConfigurationError(
            "The configured licensing public key is not a valid PEM public key."
        ) from exc

    if not isinstance(key, Ed25519PublicKey):
        raise LicenseConfigurationError("The licensing public key must be Ed25519.")
    return key


def decode_and_verify_token(token: str) -> dict[str, Any]:
    token = (token or "").strip()
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise InvalidLicenseError(
            "Invalid license format. Expected a CHL1 signed license."
        )

    payload_bytes = b64url_decode(parts[1])
    signature = b64url_decode(parts[2])

    try:
        load_public_key().verify(signature, payload_bytes)
    except InvalidSignature as exc:
        raise InvalidLicenseError(
            "The license signature is invalid or was issued by another vendor key."
        ) from exc

    try:
        claims = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidLicenseError("The license payload is not valid JSON.") from exc

    if not isinstance(claims, dict):
        raise InvalidLicenseError("The license payload must be a JSON object.")

    if canonical_json(claims) != payload_bytes:
        raise InvalidLicenseError("The license payload is not canonical.")

    return claims
