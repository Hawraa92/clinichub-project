"""
Copy the relevant lines into ClinicHub/settings.py.

Do not import this file directly.
"""

import os
from pathlib import Path


# Add to INSTALLED_APPS:
INSTALLED_APPS += [
    "licensing.apps.LicensingConfig",
]


# Add immediately AFTER django.contrib.auth.middleware.AuthenticationMiddleware:
MIDDLEWARE += [
    "licensing.middleware.LicenseEnforcementMiddleware",
]


# Add under TEMPLATES[0]["OPTIONS"]["context_processors"]:
TEMPLATES[0]["OPTIONS"]["context_processors"] += [
    "licensing.context_processors.licensing_context",
]


# Licensing settings
LICENSE_PRODUCT_CODE = "clinichub"
LICENSE_INSTALLATION_NAME = os.getenv(
    "LICENSE_INSTALLATION_NAME",
    "ClinicHub Installation",
)

# Copy only the PUBLIC key to this location on the customer server.
LICENSE_PUBLIC_KEY_FILE = BASE_DIR / "licensing_keys" / "clinichub_public_key.pem"

# Keep False during initial setup. Change to True only after the first license
# is activated and `python manage.py license_status` reports Allowed: yes.
LICENSE_ENFORCEMENT_ENABLED = (
    os.getenv("LICENSE_ENFORCEMENT_ENABLED", "0").strip().lower()
    in {"1", "true", "yes", "on"}
)

# Optional online validation. Leave empty for signed offline licenses.
LICENSE_SERVER_URL = os.getenv("LICENSE_SERVER_URL", "").strip()
LICENSE_SERVER_API_KEY = os.getenv("LICENSE_SERVER_API_KEY", "").strip()
LICENSE_ONLINE_TIMEOUT = int(os.getenv("LICENSE_ONLINE_TIMEOUT", "5"))
LICENSE_ONLINE_CHECK_HOURS = int(
    os.getenv("LICENSE_ONLINE_CHECK_HOURS", "24")
)

# Extra routes that must remain usable before activation.
LICENSE_BYPASS_PATH_PREFIXES = (
    "/accounts/",
    "/licensing/",
)

# Optional URL-to-module protection. Remove any entry that should not be gated.
LICENSE_MODULE_PATHS = {
    "/doctor/": "doctor",
    "/patient/": "patient",
    "/appointments/": "appointments",
    "/prescription/": "prescription",
    "/lab/": "lab",
    "/pharmacy/": "pharmacy",
    "/archive/": "medical_archive",
}
