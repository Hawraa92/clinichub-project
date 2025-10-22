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
# clinichub/urls.py

"""
URL configuration for ClinicHub project.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # 🏠 Home app
    path('', include('home.urls', namespace='home')),

    # 🔧 Admin site
    path('admin/', admin.site.urls),

    # 🗄️ Medical Archive
    path('archive/', include('medical_archive.urls', namespace='medical_archive')),

    # 👨‍⚕️ Doctor app
    path('doctor/', include('doctor.urls', namespace='doctor')),

    # 📅 Appointments
    path('appointments/', include('appointments.urls', namespace='appointments')),

    # 💊 Prescriptions
    path('prescription/', include('prescription.urls', namespace='prescription')),

    # 🧑‍🤝‍🧑 Patients
    path('patient/', include('patient.urls', namespace='patient')),

    # 👥 Accounts (authentication)
    path('accounts/', include('accounts.urls', namespace='accounts')),


]

# Serve media and static files in development
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

