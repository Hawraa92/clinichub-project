from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

from .services import evaluate_license, feature_enabled


def license_required(module: str | None = None):
    """Protect a view with the active license and, optionally, a module claim."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            status = evaluate_license()
            if not status.allowed:
                messages.error(request, status.message)
                return redirect("licensing:status")
            if module and not feature_enabled(module):
                raise PermissionDenied(
                    _("Your ClinicHub license does not include this module.")
                )
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
