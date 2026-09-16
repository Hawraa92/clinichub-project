from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
from uuid import UUID, uuid4

from django.test import TestCase

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .crypto import InvalidLicenseError, b64url_encode, canonical_json
from .models import Installation, LicenseAuditEvent, LicenseRecord
from .services import (
    evaluate_license,
    feature_enabled,
    install_license,
    license_limit,
)


class LicensingServiceTests(TestCase):
    def setUp(self):
        self.private_key = Ed25519PrivateKey.generate()
        public_pem = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.settings_override = self.settings(
            LICENSE_PUBLIC_KEY=public_pem.decode("utf-8"),
            LICENSE_PUBLIC_KEY_FILE="",
            LICENSE_PRODUCT_CODE="clinichub",
            LICENSE_SERVER_URL="",
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.installation = Installation.objects.create(
            id=UUID("12345678-1234-5678-1234-567812345678"),
            display_name="Test ClinicHub",
            machine_fingerprint="a" * 64,
        )

    def token(self, **updates) -> str:
        starts = date.today()
        claims = {
            "schema_version": 1,
            "license_id": str(uuid4()),
            "product": "clinichub",
            "customer_name": "Test Customer",
            "customer_email": "customer@example.com",
            "plan": "annual",
            "issued_at": datetime.now(dt_timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "not_before": starts.isoformat(),
            "expires_at": (starts + timedelta(days=365)).isoformat(),
            "grace_days": 7,
            "max_offline_days": 30,
            "installation_id": str(self.installation.pk),
            "modules": ["doctor", "pharmacy"],
            "limits": {
                "max_users": 20,
                "max_branches": 2,
                "max_pharmacies": 3,
            },
        }
        claims.update(updates)
        payload = canonical_json(claims)
        signature = self.private_key.sign(payload)
        return f"CHL1.{b64url_encode(payload)}.{b64url_encode(signature)}"

    def test_valid_signed_license_is_installed(self):
        record = install_license(self.token())

        self.assertEqual(record.customer_name, "Test Customer")
        self.assertTrue(evaluate_license().allowed)
        self.assertTrue(feature_enabled("pharmacy"))
        self.assertFalse(feature_enabled("lab"))
        self.assertEqual(license_limit("max_users"), 20)
        self.assertTrue(
            LicenseAuditEvent.objects.filter(
                event_type=LicenseAuditEvent.EventTypes.INSTALLED,
                success=True,
            ).exists()
        )

    def test_tampered_license_is_rejected(self):
        token = self.token()
        prefix, payload, signature = token.split(".")
        tampered_payload = ("A" if payload[0] != "A" else "B") + payload[1:]

        with self.assertRaises(InvalidLicenseError):
            install_license(f"{prefix}.{tampered_payload}.{signature}")

    def test_modified_stored_claims_are_blocked(self):
        record = install_license(self.token())
        LicenseRecord.objects.filter(pk=record.pk).update(
            customer_name="Modified Customer",
        )

        status = evaluate_license()

        self.assertFalse(status.allowed)
        self.assertEqual(status.code, "tampered")

    def test_modified_stored_token_is_blocked(self):
        record = install_license(self.token())
        prefix, payload, signature = record.license_token.split(".")
        modified_signature = (
            ("A" if signature[0] != "A" else "B") + signature[1:]
        )
        LicenseRecord.objects.filter(pk=record.pk).update(
            license_token=f"{prefix}.{payload}.{modified_signature}",
        )

        status = evaluate_license()

        self.assertFalse(status.allowed)
        self.assertEqual(status.code, "invalid_signature")

    def test_license_for_another_installation_is_rejected(self):
        with self.assertRaisesMessage(
            InvalidLicenseError,
            "another ClinicHub installation",
        ):
            install_license(self.token(installation_id=str(uuid4())))

    def test_expired_license_is_rejected(self):
        yesterday = date.today() - timedelta(days=1)
        with self.assertRaisesMessage(
            InvalidLicenseError,
            "grace period have expired",
        ):
            install_license(
                self.token(
                    not_before=(yesterday - timedelta(days=10)).isoformat(),
                    expires_at=yesterday.isoformat(),
                    grace_days=0,
                )
            )

    def test_perpetual_license_has_no_expiry(self):
        record = install_license(
            self.token(plan="perpetual", expires_at=None)
        )
        self.assertIsNone(record.expires_at)
        self.assertEqual(evaluate_license().code, "active")
