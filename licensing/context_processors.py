from __future__ import annotations

from django.db import OperationalError, ProgrammingError

from .services import evaluate_license


def licensing_context(_request):
    try:
        status = evaluate_license()
    except (OperationalError, ProgrammingError):
        return {
            "clinichub_license_status": None,
            "clinichub_license_valid": False,
        }
    return {
        "clinichub_license_status": status,
        "clinichub_license_valid": status.allowed,
        "clinichub_license": status.license,
    }
