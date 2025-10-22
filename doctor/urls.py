# doctor/urls.py
from django.urls import path
from django.views.generic import RedirectView
from . import views

app_name = "doctor"

urlpatterns = [
    # redirect /doctor/ → dashboard
    path("", RedirectView.as_view(pattern_name="doctor:dashboard", permanent=False)),

    # dashboard
    path("dashboard/", views.doctor_dashboard, name="dashboard"),

    # detail view (for get_absolute_url tests)
    path("<int:pk>/", views.doctor_detail, name="detail"),

    # patients list & search
    path("patients/", views.patients_list, name="patients_list"),
    path("patients/search/", views.patient_search, name="patient_search"),

    # report-search (tests expect name="report_search")
    path("patients/reports/search/", views.report_search, name="report_search"),

    # per-patient report
    path("patient/<int:patient_id>/report/", views.patient_report, name="patient_report"),
    path("patient/<int:patient_id>/report/pdf/", views.report_pdf, name="report_pdf"),
    path("patient/<int:patient_id>/report/csv/", views.report_csv, name="report_csv"),

    # doctor-level reports (KPIs, charts, table)
    path("reports/", views.doctor_reports, name="doctor_reports"),
    path("reports/export/", views.doctor_reports_export, name="reports_export"),

    # available doctors for booking
    path("available/", views.available_doctors_list, name="available_doctors"),
]
