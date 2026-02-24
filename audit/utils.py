# audit/utils.py
from __future__ import annotations

from typing import Any, Optional

from .models import AuditLog


def _get_client_ip(request) -> str | None:
    if request is None:
        return None
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        # first IP in chain
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log_action(
    *,
    request=None,
    actor=None,
    action: str = "other",
    instance: Optional[Any] = None,
    message: str = "",
    extra_data: Optional[dict] = None,
) -> AuditLog:
    """
    Reusable audit logger.
    - instance: any Django model instance (optional)
    - request: optional HttpRequest (for path/method/ip)
    - actor: optional user (if not passed, taken from request.user)
    """
    user = actor
    if user is None and request is not None:
        req_user = getattr(request, "user", None)
        if req_user is not None and getattr(req_user, "is_authenticated", False):
            user = req_user

    app_label = ""
    model_name = ""
    object_id = ""
    object_repr = ""

    if instance is not None and hasattr(instance, "_meta"):
        app_label = instance._meta.app_label
        model_name = instance._meta.model_name
        object_id = str(getattr(instance, "pk", "") or "")
        object_repr = str(instance)

    return AuditLog.objects.create(
        actor=user if getattr(user, "is_authenticated", False) else user,
        action=action,
        app_label=app_label,
        model_name=model_name,
        object_id=object_id,
        object_repr=object_repr[:255] if object_repr else "",
        path=getattr(request, "path", "") if request else "",
        method=getattr(request, "method", "") if request else "",
        ip_address=_get_client_ip(request),
        message=message[:255] if message else "",
        extra_data=extra_data or {},
    )