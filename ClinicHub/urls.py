"""
URL configuration for the ClinicHub project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.templatetags.static import static as static_url
from django.urls import include, path
from django.views.generic import RedirectView


urlpatterns = [
    # Favicon
    path(
        "favicon.ico",
        RedirectView.as_view(
            url=static_url("images/favicon.png"),
            permanent=False,
        ),
        name="favicon",
    ),

    # Django Admin
    path(
        "admin/",
        admin.site.urls,
    ),

    # Accounts
    path(
        "accounts/",
        include(
            ("accounts.urls", "accounts"),
            namespace="accounts",
        ),
    ),

    # Licensing
    path(
        "licensing/",
        include(
            ("licensing.urls", "licensing"),
            namespace="licensing",
        ),
    ),

    # Doctor
    path(
        "doctor/",
        include(
            ("doctor.urls", "doctor"),
            namespace="doctor",
        ),
    ),

    # Appointments
    path(
        "appointments/",
        include(
            ("appointments.urls", "appointments"),
            namespace="appointments",
        ),
    ),

    # Prescriptions
    path(
        "prescription/",
        include(
            ("prescription.urls", "prescription"),
            namespace="prescription",
        ),
    ),

    # Pharmacy
    path(
        "pharmacy/",
        include(
            ("pharmacy.urls", "pharmacy"),
            namespace="pharmacy",
        ),
    ),

    # Patients
    path(
        "patient/",
        include(
            ("patient.urls", "patient"),
            namespace="patient",
        ),
    ),

    # Medical Archive
    path(
        "archive/",
        include(
            ("medical_archive.urls", "medical_archive"),
            namespace="medical_archive",
        ),
    ),

    # Laboratory
    path(
        "lab/",
        include(
            ("lab.urls", "lab"),
            namespace="lab",
        ),
    ),

    # Central Analytics Dashboard
    path(
        "analytics/",
        include(
            ("analytics.urls", "analytics"),
            namespace="analytics",
        ),
    ),

    # Home — يجب أن يبقى أخيرًا لأن مساره فارغ
    path(
        "",
        include(
            ("home.urls", "home"),
            namespace="home",
        ),
    ),
]


# Serve uploaded media files during development
if settings.DEBUG or getattr(settings, "SERVE_MEDIA", False):
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )


# Serve static files during development
if settings.DEBUG:
    urlpatterns += static(
        settings.STATIC_URL,
        document_root=settings.STATIC_ROOT,
    )