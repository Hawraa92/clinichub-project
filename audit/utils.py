# audit/utils.py
from __future__ import annotations

from typing import Any, Optional

from django.contrib.auth.models import AnonymousUser

from .models import AuditLog


def _get_client_ip(request) -> str | None:
    if request is None:
        return None

    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        # first IP in chain
        ip = x_forwarded_for.split(",")[0].strip()
        return ip or None

    ip = (request.META.get("REMOTE_ADDR") or "").strip()
    return ip or None


def _normalize_actor(actor):
    """
    Return a real User instance or None.
    Avoid saving AnonymousUser object into FK field.
    """
    if actor is None:
        return None
    if isinstance(actor, AnonymousUser):
        return None
    if getattr(actor, "is_authenticated", False) is True:
        return actor
    return None


def _get_request_id(request) -> str | None:
    """
    Pull correlation id set by AuditContextMiddleware (request.audit_request_id).
    """
    if request is None:
        return None
    rid = getattr(request, "audit_request_id", None)
    if isinstance(rid, str):
        rid = rid.strip()
    return rid or None


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
    - request: optional HttpRequest (for path/method/ip + request_id)
    - actor: optional user (if not passed, taken from request.user)
    """
    user = _normalize_actor(actor)
    if user is None and request is not None:
        user = _normalize_actor(getattr(request, "user", None))

    app_label = ""
    model_name = ""
    object_id = ""
    object_repr = ""

    if instance is not None and hasattr(instance, "_meta"):
        app_label = getattr(instance._meta, "app_label", "") or ""
        model_name = getattr(instance._meta, "model_name", "") or ""
        object_id = str(getattr(instance, "pk", "") or "")
        object_repr = str(instance or "")

    ip = _get_client_ip(request)

    # ✅ Always attach request_id (if present) to extra_data for correlation
    rid = _get_request_id(request)
    base_extra: dict = {"request_id": rid} if rid else {}
    final_extra: dict = {**base_extra, **(extra_data or {})}  # caller can override if they want

    return AuditLog.objects.create(
        actor=user,  # None if anonymous
        action=(action or "other")[:20],
        app_label=app_label[:100],
        model_name=model_name[:100],
        object_id=object_id[:64],
        object_repr=object_repr[:255] if object_repr else "",
        path=(getattr(request, "path", "") or "")[:500] if request else "",
        method=(getattr(request, "method", "") or "")[:10] if request else "",
        ip_address=ip,  # None is allowed
        message=(message or "")[:255],
        extra_data=final_extra,
    )