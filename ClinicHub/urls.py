"""
URL configuration for ClinicHub project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import: from my_app import views
    2. Add a URL to urlpatterns: path('', views.home, name='home')
Class-based views
    1. Add an import: from other_app.views import Home
    2. Add a URL to urlpatterns: path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns: path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.http import HttpResponseRedirect
from django.templatetags.static import static as static_url
from django.urls import include, path, re_path
from django.views.static import serve


def favicon_view(request):
    """
    Serve favicon via Django static helper at request time
    to avoid ManifestStaticFilesStorage import-time errors.
    """
    return HttpResponseRedirect(static_url("images/favicon.png"))


urlpatterns = [
    # ✅ Favicon
    path("favicon.ico", favicon_view, name="favicon"),

    # 🏠 Home
    path("", include(("home.urls", "home"), namespace="home")),

    # 🔧 Admin
    path("admin/", admin.site.urls),

    # 👥 Accounts
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),

    # 👨‍⚕️ Doctor
    path("doctor/", include(("doctor.urls", "doctor"), namespace="doctor")),

    # 📅 Appointments
    path(
        "appointments/",
        include(("appointments.urls", "appointments"), namespace="appointments"),
    ),

    # 💊 Prescriptions
    path(
        "prescription/",
        include(("prescription.urls", "prescription"), namespace="prescription"),
    ),

    # 🧑‍🤝‍🧑 Patients
    path("patient/", include(("patient.urls", "patient"), namespace="patient")),

    # 🗄️ Medical Archive
    path(
        "archive/",
        include(("medical_archive.urls", "medical_archive"), namespace="medical_archive"),
    ),

    # 🧪 Lab
    path("lab/", include(("lab.urls", "lab"), namespace="lab")),
]


# ✅ Serve MEDIA + STATIC in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += staticfiles_urlpatterns()

# ✅ Serve MEDIA in production only when explicitly enabled
elif getattr(settings, "SERVE_MEDIA", False):
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]