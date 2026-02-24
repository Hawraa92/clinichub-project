from django.urls import path
from . import views

app_name = "prescription"

urlpatterns = [
    # Public verification (used by QR code)
    path("verify/<path:token>/", views.verify, name="verify"),

    # OPTIONAL: public PDF download (token-gated) — works only if PRESCRIPTION_PUBLIC_DOWNLOAD=True
    path("public-pdf/<path:token>/", views.public_pdf, name="public_pdf"),

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

    # PDF download (private)
    path("<int:pk>/pdf/", views.download_pdf_prescription, name="download_pdf"),
    # OPTIONAL inline view:
    # path("<int:pk>/pdf/inline/", views.prescription_pdf, name="pdf_inline"),

    # Send via WhatsApp (private)
    path("<int:pk>/whatsapp/", views.send_prescription_whatsapp, name="send_whatsapp"),
]
