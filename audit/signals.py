# audit/signals.py
from __future__ import annotations

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .utils import log_event


@receiver(user_logged_in)
def _audit_login(sender, request, user, **kwargs):
    if request is not None:
        log_event(request, "login", message="User logged in")


@receiver(user_logged_out)
def _audit_logout(sender, request, user, **kwargs):
    if request is not None:
        log_event(request, "logout", message="User logged out")