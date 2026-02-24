# clinichub/wsgi.py
"""
WSGI config for ClinicHub project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see:
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

# ✅ FIXED: Linux/Render is case-sensitive, so use the real module path
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ClinicHub.settings")

application = get_wsgi_application()
