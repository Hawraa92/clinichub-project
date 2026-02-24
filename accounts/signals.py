# accounts/signals.py
from __future__ import annotations

import logging
import sys
from datetime import timedelta
from typing import Any, Optional

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.core.mail import send_mail
from django.dispatch import receiver
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_naive, make_aware

logger = logging.getLogger(__name__)


def _is_testing() -> bool:
    """
    Disable notifications during Django/pytest runs.
    """
    argv = " ".join(sys.argv).lower()
    return (" test " in f" {argv} ") or ("pytest" in argv)


def _get_client_ip(request) -> str:
    """
    Best-effort client IP extraction (supports proxy headers).
    """
    if not request:
        return "unknown"

    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        # take first IP in the chain
        return (xff.split(",")[0] or "").strip() or "unknown"

    return request.META.get("REMOTE_ADDR") or "unknown"


def _session_throttle_ok(request, now, seconds: int) -> bool:
    """
    Prevent sending multiple emails per session in a very short period.
    """
    if not request or not hasattr(request, "session") or seconds <= 0:
        return True

    key = "_admin_login_notify_at"
    raw = request.session.get(key)

    last_dt: Optional[timezone.datetime] = None
    if isinstance(raw, str) and raw.strip():
        last_dt = parse_datetime(raw.strip())
        if last_dt and is_naive(last_dt):
            last_dt = make_aware(last_dt)

    if last_dt and (now - last_dt) < timedelta(seconds=seconds):
        return False

    request.session[key] = now.isoformat()
    request.session.modified = True
    return True


@receiver(user_logged_in)
def notify_admin_on_login(sender, request, user, **kwargs: Any) -> None:
    """
    Optional admin email notification on login.

    ✅ Off by default:
      - set LOGIN_NOTIFY_ADMIN = True to enable

    ✅ Safe:
      - disabled during tests
      - requires ADMIN_EMAIL
      - optional: only staff logins (LOGIN_NOTIFY_ONLY_STAFF=True)
      - session throttle (LOGIN_NOTIFY_THROTTLE_SECONDS=60)
    """
    if _is_testing():
        return

    if not getattr(settings, "LOGIN_NOTIFY_ADMIN", False):
        return

    admin_email = (getattr(settings, "ADMIN_EMAIL", "") or "").strip()
    if not admin_email:
        return

    if getattr(settings, "LOGIN_NOTIFY_ONLY_STAFF", False):
        if not (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)):
            return

    now = timezone.now()
    throttle_seconds = int(getattr(settings, "LOGIN_NOTIFY_THROTTLE_SECONDS", 60) or 0)
    if not _session_throttle_ok(request, now, throttle_seconds):
        return

    project = getattr(settings, "PROJECT_NAME", "ClinicHub")
    role = getattr(user, "role", None) or "unknown"

    subject = f"[{project}] User Login: {user.get_full_name() or user.email}"
    message = (
        f"User: {user.get_full_name() or user.username} ({user.email})\n"
        f"Role: {role}\n"
        f"IP: {_get_client_ip(request)}\n"
        f"Time: {now.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[admin_email],
            fail_silently=bool(getattr(settings, "LOGIN_NOTIFY_FAIL_SILENTLY", True)),
        )
    except Exception as exc:  # extra safety
        logger.warning("Admin login notification failed: %s", exc)