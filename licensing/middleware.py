from __future__ import annotations

from django.conf import settings
from django.db import OperationalError, ProgrammingError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse

from .services import evaluate_license, feature_enabled


DEFAULT_BYPASS_PREFIXES = (
    "/licensing/",
    "/accounts/",
    "/admin/login/",
    "/admin/logout/",
    "/static/",
    "/media/",
    "/favicon.ico",
    "/health/",
)


class LicenseEnforcementMiddleware:
    """
    Enforce the installed license for normal application requests.

    Add it after AuthenticationMiddleware. Enforcement is disabled unless
    LICENSE_ENFORCEMENT_ENABLED=True, which prevents accidental lockout during
    first-time installation.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "LICENSE_ENFORCEMENT_ENABLED", False):
            return self.get_response(request)

        path = request.path_info or "/"
        configured = getattr(settings, "LICENSE_BYPASS_PATH_PREFIXES", ())
        prefixes = tuple(DEFAULT_BYPASS_PREFIXES) + tuple(configured)
        if any(path.startswith(prefix) for prefix in prefixes if prefix):
            return self.get_response(request)

        try:
            status = evaluate_license()
        except (OperationalError, ProgrammingError):
            return self._database_not_ready_response(request)

        if status.allowed:
            request.clinichub_license = status.license
            request.clinichub_license_status = status
            missing_module = self._missing_module(path)
            if missing_module:
                message = (
                    f"The active ClinicHub license does not include the "
                    f"'{missing_module}' module."
                )
                if self._wants_json(request):
                    return JsonResponse(
                        {
                            "detail": message,
                            "license_status": "module_not_licensed",
                        },
                        status=403,
                    )
                return HttpResponse(
                    message,
                    status=403,
                    content_type="text/plain; charset=utf-8",
                )
            return self.get_response(request)

        if self._wants_json(request):
            return JsonResponse(
                {
                    "detail": status.message,
                    "license_status": status.code,
                },
                status=403,
            )

        try:
            status_url = reverse("licensing:status")
        except NoReverseMatch:
            return HttpResponse(
                f"ClinicHub license unavailable: {status.message}",
                status=503,
                content_type="text/plain; charset=utf-8",
            )
        return redirect(status_url)

    @staticmethod
    def _wants_json(request) -> bool:
        accept = request.headers.get("Accept", "")
        return (
            request.path_info.startswith("/api/")
            or "application/json" in accept.lower()
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        )

    @staticmethod
    def _missing_module(path: str) -> str | None:
        module_paths = getattr(settings, "LICENSE_MODULE_PATHS", {})
        for prefix, module_name in module_paths.items():
            if path.startswith(prefix) and not feature_enabled(module_name):
                return str(module_name)
        return None

    def _database_not_ready_response(self, request):
        message = (
            "The licensing database tables are unavailable. "
            "Run: python manage.py migrate licensing"
        )
        if self._wants_json(request):
            return JsonResponse({"detail": message}, status=503)
        return HttpResponse(
            message,
            status=503,
            content_type="text/plain; charset=utf-8",
        )
