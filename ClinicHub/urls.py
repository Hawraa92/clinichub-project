"""
URL configuration for ClinicHub project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""




from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from django.views.generic import RedirectView
from django.templatetags.static import static as static_url
from django.contrib.staticfiles.urls import staticfiles_urlpatterns


urlpatterns = [
    # ✅ Favicon (المتصفح يطلب /favicon.ico تلقائياً)
    path(
        "favicon.ico",
        RedirectView.as_view(url=static_url("images/favicon.png"), permanent=False),
        name="favicon",
    ),

    # 🏠 Home
    path("", include(("home.urls", "home"), namespace="home")),

    # 🔧 Admin
    path("admin/", admin.site.urls),

    # 👥 Accounts
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),

    # 👨‍⚕️ Doctor
    path("doctor/", include(("doctor.urls", "doctor"), namespace="doctor")),

    # 📅 Appointments
    path("appointments/", include(("appointments.urls", "appointments"), namespace="appointments")),

    # 💊 Prescriptions
    path("prescription/", include(("prescription.urls", "prescription"), namespace="prescription")),

    # 🧑‍🤝‍🧑 Patients
    path("patient/", include(("patient.urls", "patient"), namespace="patient")),

    # 🗄️ Medical Archive
    path("archive/", include(("medical_archive.urls", "medical_archive"), namespace="medical_archive")),

    # 🧪 Lab  ✅ (أضفنا namespace حتى يصير consistent)
    path("lab/", include(("lab.urls", "lab"), namespace="lab")),
]


# ✅ Serve MEDIA in dev (أو إذا محددة SERVE_MEDIA=True)
if settings.DEBUG or getattr(settings, "SERVE_MEDIA", False):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# ✅ Serve STATIC in dev (أفضل من static(..., STATIC_ROOT) أثناء التطوير)
if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
