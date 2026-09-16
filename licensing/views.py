from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .access import is_license_administrator, require_license_administrator
from .crypto import LicenseError
from .forms import LicenseActivationForm
from .models import Installation, LicenseAuditEvent
from .services import (
    evaluate_license,
    install_license,
    synchronize_license,
)


def _client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


@login_required
def license_status(request):
    installation = Installation.get_current()
    status = evaluate_license()
    recent_events = LicenseAuditEvent.objects.select_related(
        "license",
        "actor",
    )[:20]
    return render(
        request,
        "licensing/status.html",
        {
            "installation": installation,
            "license_status": status,
            "license": status.license,
            "recent_events": recent_events,
            "can_manage_license": is_license_administrator(request.user),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def activate_license(request):
    require_license_administrator(request.user)
    installation = Installation.get_current()
    form = LicenseActivationForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            record = install_license(
                form.cleaned_data["license_token"],
                actor=request.user,
                ip_address=_client_ip(request),
            )
        except LicenseError as exc:
            form.add_error("license_token", str(exc))
        else:
            messages.success(
                request,
                f"License {record.license_id} was activated successfully.",
            )
            return redirect("licensing:status")

    return render(
        request,
        "licensing/activate.html",
        {
            "form": form,
            "installation": installation,
        },
    )


@login_required
def installation_request(request):
    require_license_administrator(request.user)
    installation = Installation.get_current()
    response = JsonResponse(
        {
            "schema_version": 1,
            "product": "clinichub",
            "installation_id": str(installation.pk),
            "installation_name": installation.display_name,
            "machine_fingerprint": installation.machine_fingerprint,
        },
        json_dumps_params={"indent": 2, "ensure_ascii": False},
    )
    response["Content-Disposition"] = (
        'attachment; filename="clinichub-installation-request.json"'
    )
    return response


@login_required
@require_POST
def sync_license(request):
    require_license_administrator(request.user)
    try:
        record = synchronize_license()
    except LicenseError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"License {record.license_id} was synchronized successfully.",
        )
    return redirect("licensing:status")


@login_required
def status_api(request):
    status = evaluate_license()
    payload = status.public_dict()
    payload["installation_id"] = str(Installation.get_current().pk)
    if status.license is not None:
        payload.update(
            {
                "license_id": str(status.license.license_id),
                "customer_name": status.license.customer_name,
                "plan": status.license.plan,
                "expires_at": (
                    status.license.expires_at.isoformat()
                    if status.license.expires_at
                    else None
                ),
                "modules": status.license.modules,
                "limits": status.license.limits,
            }
        )
    return JsonResponse(payload, status=200 if status.allowed else 403)
