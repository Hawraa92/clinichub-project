# accounts/signals.py

from django.conf import settings
from django.core.mail import send_mail
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_in
from django.utils import timezone

@receiver(user_logged_in)
def notify_admin_on_login(sender, request, user, **kwargs):
    """
    Send an email notification to the admin each time any user logs in.
    """
    subject = f"User Login: {user.get_full_name() or user.email}"
    message = (
        f"The user {user.username} ({user.email}) just logged in.\n"
        f"IP Address: {request.META.get('REMOTE_ADDR')}\n"
        f"Time: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [settings.ADMIN_EMAIL],
        fail_silently=True,
    )
