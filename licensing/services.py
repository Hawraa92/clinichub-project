from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone as dt_timezone
from typing import Any
from urllib import error, request as urlrequest
from uuid import UUID

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .crypto import (
    InvalidLicenseError,
    LicenseConfigurationError,
    LicenseError,
    decode_and_verify_token,
)
from .models import Installation, LicenseAuditEvent, LicenseRecord


REQUIRED_CLAIMS = {
    "schema_version",
    "license_id",
    "product",
    "customer_name",
    "plan",
    "issued_at",
    "not_before",
    "installation_id",
    "modules",
    "limits",
}


class LicenseLimitExceeded(LicenseError):
    pass


@dataclass(frozen=True)
class LicenseStatus:
    code: str
    allowed: bool
    message: str
    license: LicenseRecord | None = None
    days_remaining: int | None = None
    in_grace_period: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "allowed": self.allowed,
            "message": self.message,
            "days_remaining": self.days_remaining,
            "in_grace_period": self.in_grace_period,
        }


def _parse_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise InvalidLicenseError(f"{field_name} must be an ISO date.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidLicenseError(f"{field_name} is not a valid ISO date.") from exc


def _parse_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise InvalidLicenseError(f"{field_name} must be an ISO datetime.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidLicenseError(
            f"{field_name} is not a valid ISO datetime."
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


def _positive_int(value: Any, field_name: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise InvalidLicenseError(f"{field_name} must be a non-negative integer.")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidLicenseError(
            f"{field_name} must be a non-negative integer."
        ) from exc
    if result < 0:
        raise InvalidLicenseError(f"{field_name} must be a non-negative integer.")
    return result


def validate_claims(
    claims: dict[str, Any],
    installation: Installation,
) -> dict[str, Any]:
    missing = sorted(REQUIRED_CLAIMS.difference(claims))
    if missing:
        raise InvalidLicenseError(
            f"The license is missing required fields: {', '.join(missing)}."
        )

    if claims["schema_version"] != 1:
        raise InvalidLicenseError("Unsupported license schema version.")

    expected_product = getattr(settings, "LICENSE_PRODUCT_CODE", "clinichub")
    if claims["product"] != expected_product:
        raise InvalidLicenseError(
            f"This license is for '{claims['product']}', not '{expected_product}'."
        )

    try:
        license_id = UUID(str(claims["license_id"]))
        installation_id = UUID(str(claims["installation_id"]))
    except (TypeError, ValueError, AttributeError) as exc:
        raise InvalidLicenseError(
            "The license or installation identifier is invalid."
        ) from exc

    if installation_id != installation.pk:
        raise InvalidLicenseError(
            "This license belongs to another ClinicHub installation."
        )

    customer_name = str(claims["customer_name"]).strip()
    if not customer_name:
        raise InvalidLicenseError("The customer name cannot be empty.")

    plan = str(claims["plan"]).strip().lower()
    valid_plans = {value for value, _label in LicenseRecord.Plans.choices}
    if plan not in valid_plans:
        raise InvalidLicenseError("The license plan is not supported.")

    issued_at = _parse_datetime(claims["issued_at"], "issued_at")
    not_before = _parse_date(claims["not_before"], "not_before")
    expires_at = (
        _parse_date(claims["expires_at"], "expires_at")
        if claims.get("expires_at")
        else None
    )
    if plan != LicenseRecord.Plans.PERPETUAL and expires_at is None:
        raise InvalidLicenseError(
            "A non-perpetual license must include an expiry date."
        )
    if expires_at is not None and expires_at < not_before:
        raise InvalidLicenseError("The expiry date is earlier than the start date.")

    modules = claims["modules"]
    if not isinstance(modules, list) or not all(
        isinstance(module, str) and module.strip() for module in modules
    ):
        raise InvalidLicenseError("modules must be a list of non-empty strings.")
    modules = sorted({module.strip().lower() for module in modules})

    limits = claims["limits"]
    if not isinstance(limits, dict):
        raise InvalidLicenseError("limits must be a JSON object.")
    clean_limits = {
        str(key).strip().lower(): _positive_int(value, f"limits.{key}", 0)
        for key, value in limits.items()
    }

    grace_days = _positive_int(claims.get("grace_days"), "grace_days", 0)
    max_offline_days = _positive_int(
        claims.get("max_offline_days"),
        "max_offline_days",
        30,
    )

    return {
        **claims,
        "license_id": license_id,
        "installation_id": installation_id,
        "customer_name": customer_name,
        "customer_email": str(claims.get("customer_email", "")).strip(),
        "plan": plan,
        "issued_at": issued_at,
        "not_before": not_before,
        "expires_at": expires_at,
        "modules": modules,
        "limits": clean_limits,
        "grace_days": grace_days,
        "max_offline_days": max_offline_days,
    }


def get_active_license() -> LicenseRecord | None:
    return (
        LicenseRecord.objects.select_related("installation")
        .filter(is_active=True, is_revoked=False)
        .order_by("-activated_at")
        .first()
    )


def _stored_record_matches_signed_claims(
    record: LicenseRecord,
    claims: dict[str, Any],
) -> bool:
    signed_values = {
        "license_id": claims["license_id"],
        "installation_id": claims["installation_id"],
        "product": claims["product"],
        "customer_name": claims["customer_name"],
        "customer_email": claims["customer_email"],
        "plan": claims["plan"],
        "issued_at": claims["issued_at"],
        "not_before": claims["not_before"],
        "expires_at": claims["expires_at"],
        "grace_days": claims["grace_days"],
        "max_offline_days": claims["max_offline_days"],
        "modules": sorted(claims["modules"]),
        "limits": claims["limits"],
    }
    stored_values = {
        "license_id": record.license_id,
        "installation_id": record.installation_id,
        "product": record.product,
        "customer_name": record.customer_name,
        "customer_email": record.customer_email,
        "plan": record.plan,
        "issued_at": record.issued_at,
        "not_before": record.not_before,
        "expires_at": record.expires_at,
        "grace_days": record.grace_days,
        "max_offline_days": record.max_offline_days,
        "modules": sorted(record.modules),
        "limits": record.limits,
    }
    return stored_values == signed_values


def evaluate_license(
    license_record: LicenseRecord | None = None,
    *,
    today: date | None = None,
) -> LicenseStatus:
    record = license_record or get_active_license()
    if record is None:
        return LicenseStatus(
            code="not_activated",
            allowed=False,
            message="No active ClinicHub license is installed.",
        )

    if record.is_revoked or not record.is_active:
        return LicenseStatus(
            code="revoked",
            allowed=False,
            message="The ClinicHub license is inactive or revoked.",
            license=record,
        )

    try:
        signed_claims = validate_claims(
            decode_and_verify_token(record.license_token),
            record.installation,
        )
    except LicenseConfigurationError as exc:
        return LicenseStatus(
            code="configuration_error",
            allowed=False,
            message=str(exc),
            license=record,
        )
    except InvalidLicenseError:
        return LicenseStatus(
            code="invalid_signature",
            allowed=False,
            message="The stored ClinicHub license signature is invalid.",
            license=record,
        )

    if not _stored_record_matches_signed_claims(record, signed_claims):
        return LicenseStatus(
            code="tampered",
            allowed=False,
            message=(
                "The stored license data does not match its signed payload. "
                "Reinstall the original license."
            ),
            license=record,
        )

    current_date = today or timezone.localdate()
    if current_date < record.not_before:
        return LicenseStatus(
            code="not_started",
            allowed=False,
            message=f"The license starts on {record.not_before.isoformat()}.",
            license=record,
        )

    if record.expires_at is not None:
        days_remaining = (record.expires_at - current_date).days
        if current_date > record.expires_at:
            grace_end = record.expires_at + timedelta(days=record.grace_days)
            if current_date <= grace_end:
                return LicenseStatus(
                    code="grace",
                    allowed=True,
                    message=(
                        "The license has expired and is operating within its "
                        "grace period."
                    ),
                    license=record,
                    days_remaining=(grace_end - current_date).days,
                    in_grace_period=True,
                )
            return LicenseStatus(
                code="expired",
                allowed=False,
                message="The ClinicHub license has expired.",
                license=record,
                days_remaining=days_remaining,
            )
    else:
        days_remaining = None

    server_url = getattr(settings, "LICENSE_SERVER_URL", "").strip()
    if server_url and record.max_offline_days:
        last_contact = record.last_online_success_at or record.activated_at
        offline_deadline = last_contact + timedelta(days=record.max_offline_days)
        if timezone.now() > offline_deadline:
            return LicenseStatus(
                code="online_check_required",
                allowed=False,
                message=(
                    "The maximum offline period has elapsed. "
                    "Connect the server and synchronize the license."
                ),
                license=record,
                days_remaining=days_remaining,
            )

    return LicenseStatus(
        code="active",
        allowed=True,
        message="The ClinicHub license is active.",
        license=record,
        days_remaining=days_remaining,
    )


def install_license(
    token: str,
    *,
    actor=None,
    ip_address: str | None = None,
) -> LicenseRecord:
    installation = Installation.get_current()
    try:
        claims = validate_claims(decode_and_verify_token(token), installation)
    except LicenseError as exc:
        LicenseAuditEvent.objects.create(
            event_type=LicenseAuditEvent.EventTypes.REJECTED,
            actor=actor if getattr(actor, "is_authenticated", False) else None,
            success=False,
            message=str(exc),
            ip_address=ip_address,
        )
        raise

    today = timezone.localdate()
    if today < claims["not_before"]:
        raise InvalidLicenseError(
            f"This license does not start until {claims['not_before'].isoformat()}."
        )
    if claims["expires_at"] is not None:
        grace_end = claims["expires_at"] + timedelta(days=claims["grace_days"])
        if today > grace_end:
            raise InvalidLicenseError("This license and its grace period have expired.")

    now = timezone.now()
    with transaction.atomic():
        LicenseRecord.objects.select_for_update().filter(
            installation=installation,
            is_active=True,
        ).update(is_active=False)

        record, _created = LicenseRecord.objects.update_or_create(
            license_id=claims["license_id"],
            defaults={
                "installation": installation,
                "product": claims["product"],
                "customer_name": claims["customer_name"],
                "customer_email": claims["customer_email"],
                "plan": claims["plan"],
                "issued_at": claims["issued_at"],
                "not_before": claims["not_before"],
                "expires_at": claims["expires_at"],
                "grace_days": claims["grace_days"],
                "max_offline_days": claims["max_offline_days"],
                "modules": claims["modules"],
                "limits": claims["limits"],
                "claims": {
                    key: value
                    for key, value in claims.items()
                    if key not in {"license_id", "installation_id"}
                    and not isinstance(value, (date, datetime, UUID))
                },
                "license_token": token.strip(),
                "is_active": True,
                "is_revoked": False,
                "activated_at": now,
                "activated_by": (
                    actor if getattr(actor, "is_authenticated", False) else None
                ),
                "last_verified_at": now,
                "last_online_success_at": None,
                "last_error": "",
            },
        )

        LicenseAuditEvent.objects.create(
            event_type=LicenseAuditEvent.EventTypes.INSTALLED,
            license=record,
            actor=record.activated_by,
            success=True,
            message="A signed ClinicHub license was installed.",
            metadata={
                "plan": record.plan,
                "modules": record.modules,
            },
            ip_address=ip_address,
        )

    return record


def feature_enabled(module_name: str) -> bool:
    status = evaluate_license()
    if not status.allowed or status.license is None:
        return False
    wanted = module_name.strip().lower()
    modules = {str(module).lower() for module in status.license.modules}
    return "*" in modules or wanted in modules


def license_limit(name: str, default: int | None = None) -> int | None:
    status = evaluate_license()
    if not status.allowed or status.license is None:
        return default
    value = status.license.limits.get(name.strip().lower(), default)
    if value in (None, 0):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def current_usage(limit_name: str) -> int:
    key = limit_name.strip().lower()
    if key == "max_users":
        return get_user_model().objects.filter(is_active=True).count()

    model_map = {
        "max_branches": ("hospital", "Branch"),
        "max_pharmacies": ("pharmacy", "Pharmacy"),
    }
    app_model = model_map.get(key)
    if app_model is None:
        raise LicenseLimitExceeded(f"Unknown license limit: {limit_name}.")

    model = apps.get_model(*app_model)
    queryset = model.objects.all()
    if any(field.name == "is_active" for field in model._meta.fields):
        queryset = queryset.filter(is_active=True)
    return queryset.count()


def assert_can_add(limit_name: str, *, increment: int = 1) -> None:
    maximum = license_limit(limit_name)
    if maximum is None:
        return
    usage = current_usage(limit_name)
    if usage + increment <= maximum:
        return

    active = get_active_license()
    LicenseAuditEvent.objects.create(
        event_type=LicenseAuditEvent.EventTypes.LIMIT_BLOCKED,
        license=active,
        success=False,
        message=f"{limit_name} limit reached ({usage}/{maximum}).",
        metadata={"limit": limit_name, "usage": usage, "maximum": maximum},
    )
    raise LicenseLimitExceeded(
        f"The license limit '{limit_name}' has been reached ({usage}/{maximum})."
    )


def synchronize_license() -> LicenseRecord:
    record = get_active_license()
    if record is None:
        raise InvalidLicenseError("No active license is installed.")

    server_url = getattr(settings, "LICENSE_SERVER_URL", "").strip()
    if not server_url:
        raise LicenseConfigurationError("LICENSE_SERVER_URL is not configured.")

    payload = json.dumps(
        {
            "product": record.product,
            "license_id": str(record.license_id),
            "installation_id": str(record.installation_id),
            "machine_fingerprint": record.installation.machine_fingerprint,
        }
    ).encode("utf-8")
    api_key = getattr(settings, "LICENSE_SERVER_API_KEY", "").strip()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    outgoing = urlrequest.Request(
        server_url,
        data=payload,
        headers=headers,
        method="POST",
    )
    timeout = int(getattr(settings, "LICENSE_ONLINE_TIMEOUT", 5))

    try:
        with urlrequest.urlopen(outgoing, timeout=timeout) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        record.last_error = f"Online verification failed: {exc}"
        record.save(update_fields=["last_error", "updated_at"])
        LicenseAuditEvent.objects.create(
            event_type=LicenseAuditEvent.EventTypes.ONLINE_FAILED,
            license=record,
            success=False,
            message=record.last_error,
        )
        raise LicenseError(record.last_error) from exc

    if response_data.get("revoked") is True:
        record.is_revoked = True
        record.is_active = False
        record.last_error = str(response_data.get("message") or "License revoked.")
        record.save(
            update_fields=[
                "is_revoked",
                "is_active",
                "last_error",
                "updated_at",
            ]
        )
        LicenseAuditEvent.objects.create(
            event_type=LicenseAuditEvent.EventTypes.REVOKED,
            license=record,
            success=False,
            message=record.last_error,
        )
        raise InvalidLicenseError(record.last_error)

    refreshed_token = response_data.get("license_token")
    if refreshed_token:
        record = install_license(refreshed_token)

    now = timezone.now()
    record.last_online_success_at = now
    record.last_verified_at = now
    record.next_online_check_at = now + timedelta(
        hours=int(getattr(settings, "LICENSE_ONLINE_CHECK_HOURS", 24))
    )
    record.last_error = ""
    record.save(
        update_fields=[
            "last_online_success_at",
            "last_verified_at",
            "next_online_check_at",
            "last_error",
            "updated_at",
        ]
    )
    LicenseAuditEvent.objects.create(
        event_type=LicenseAuditEvent.EventTypes.ONLINE_OK,
        license=record,
        success=True,
        message="Online license verification succeeded.",
    )
    return record
