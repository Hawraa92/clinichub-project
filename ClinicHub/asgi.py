# clinicHub/asgi.py
"""
ASGI config for ClinicHub project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see:
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

# ✅ FIXED: Linux/Render is case-sensitive, so use the real module path
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ClinicHub.settings")

application = get_asgi_application()
