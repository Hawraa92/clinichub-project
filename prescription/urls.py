# File: prescription/urls.py

from django.urls import path
from . import views

app_name = "prescription"

urlpatterns = [
    # Public verification (used by QR code)
    # Use <path:token> to safely accept tokens that may contain "/"
    path("verify/<path:token>/", views.verify, name="verify"),

    # New prescription (generic)
    path("new/", views.new_prescription, name="new_prescription"),

    # List all prescriptions
    path("", views.prescription_list, name="list"),

    # Create a prescription for a specific appointment
    path("create/<int:appointment_id>/", views.create_prescription, name="create"),

    # Prescription detail (private)
    path("<int:pk>/", views.prescription_detail, name="prescription_detail"),

    # Edit / Delete
    path("<int:pk>/edit/", views.edit_prescription, name="edit"),
    path("<int:pk>/delete/", views.delete_prescription, name="delete"),

    # PDF download
    path("<int:pk>/pdf/", views.download_pdf_prescription, name="download_pdf"),
    path(
        "<int:pk>/attachment/<str:field_name>/",
        views.prescription_attachment,
        name="attachment",
    ),

    # Send via WhatsApp
    path("<int:pk>/whatsapp/", views.send_prescription_whatsapp, name="send_whatsapp"),
]
