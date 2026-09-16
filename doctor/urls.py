from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import path
from django.views.generic import RedirectView

from . import views


app_name = "doctor"


# =========================================================
# Permission names
# =========================================================
PERM_VIEW_ANALYTICS = "doctor.view_doctoranalyticsaccess"
PERM_GENERATE_PATIENT_REPORT = "doctor.view_patientreportexportaccess"
PERM_VIEW_LAB_ORDER = "lab.view_laborder"
PERM_ADD_LAB_ORDER = "lab.add_laborder"


# Reusable permission decorators.
# raise_exception=True displays the custom ClinicHub 403 page.
analytics_required = permission_required(
    PERM_VIEW_ANALYTICS,
    raise_exception=True,
)

patient_report_required = permission_required(
    PERM_GENERATE_PATIENT_REPORT,
    raise_exception=True,
)

lab_order_view_required = permission_required(
    PERM_VIEW_LAB_ORDER,
    raise_exception=True,
)

lab_order_add_required = permission_required(
    PERM_ADD_LAB_ORDER,
    raise_exception=True,
)


# =========================================================
# Optional LAB integration (safe import)
# =========================================================
try:
    from lab import views as lab_views  # type: ignore
except Exception:
    lab_views = None


def _lab_views_ready() -> bool:
    if not lab_views:
        return False

    required = (
        "doctor_orders_inbox",
        "doctor_create_lab_order",
        "doctor_order_detail",
    )

    return all(
        hasattr(lab_views, function_name)
        for function_name in required
    )


HAS_LAB_VIEWS = _lab_views_ready()


# =========================================================
# Lab fallback handlers (lab disabled)
# =========================================================
def _lab_not_available(
    request: HttpRequest,
    *_args,
    **_kwargs,
) -> HttpResponse:
    messages.info(
        request,
        "Lab module is not enabled in this deployment.",
    )
    return redirect("doctor:lab_orders")


def _lab_order_detail_fallback(
    request: HttpRequest,
    order_id: int,
) -> HttpResponse:
    return views.doctor_lab_request_detail(
        request,
        request_id=order_id,
    )


# =========================================================
# Lab proxies (lab enabled)
# =========================================================
def _lab_orders_inbox_proxy(
    request: HttpRequest,
    *args,
    **kwargs,
) -> HttpResponse:
    return lab_views.doctor_orders_inbox(  # type: ignore
        request,
        *args,
        **kwargs,
    )


def _lab_order_create_proxy(
    request: HttpRequest,
    patient_id: int,
    *args,
    **kwargs,
) -> HttpResponse:
    """
    Support different signatures across lab implementations.
    """
    try:
        return lab_views.doctor_create_lab_order(  # type: ignore
            request,
            patient_id=patient_id,
            *args,
            **kwargs,
        )
    except TypeError:
        try:
            return lab_views.doctor_create_lab_order(  # type: ignore
                request,
                pk=patient_id,
                *args,
                **kwargs,
            )
        except TypeError:
            return lab_views.doctor_create_lab_order(  # type: ignore
                request,
                patient_id,
                *args,
                **kwargs,
            )


def _lab_order_detail_proxy(
    request: HttpRequest,
    order_id: int,
    *args,
    **kwargs,
) -> HttpResponse:
    """
    Support different keyword names across lab implementations.
    """
    try:
        return lab_views.doctor_order_detail(  # type: ignore
            request,
            order_id=order_id,
            *args,
            **kwargs,
        )
    except TypeError:
        pass

    try:
        return lab_views.doctor_order_detail(  # type: ignore
            request,
            request_id=order_id,
            *args,
            **kwargs,
        )
    except TypeError:
        pass

    try:
        return lab_views.doctor_order_detail(  # type: ignore
            request,
            pk=order_id,
            *args,
            **kwargs,
        )
    except TypeError:
        pass

    return lab_views.doctor_order_detail(  # type: ignore
        request,
        order_id,
        *args,
        **kwargs,
    )


# =========================================================
# Constants (so paths never diverge)
# =========================================================
VISIT_PATH = "visit/<int:appointment_id>/"
AI_PATH = "visit/<int:appointment_id>/ai-assist/"
PATIENTS_PATH = "patients/"
AVAILABLE_PATH = "available/"

# Doctor-only diabetes screening/input page (per patient)
DOCTOR_DIABETES_PATH = "patient/<int:patient_id>/diabetes/"


# =========================================================
# Prescription detail alias proxy
# =========================================================
def _prescription_detail_proxy(
    request: HttpRequest,
    presc_id: int,
    *args,
    **kwargs,
) -> HttpResponse:
    candidates = (
        "prescription_detail",
        "doctor_prescription_detail",
        "view_prescription",
        "prescription_view",
        "prescription_detail_view",
    )

    for function_name in candidates:
        view_function = getattr(
            views,
            function_name,
            None,
        )

        if not callable(view_function):
            continue

        for keyword_name in (
            "presc_id",
            "prescription_id",
            "pk",
            "id",
        ):
            try:
                call_kwargs = dict(kwargs)
                call_kwargs[keyword_name] = presc_id
                return view_function(
                    request,
                    *args,
                    **call_kwargs,
                )
            except TypeError:
                continue

        try:
            return view_function(
                request,
                presc_id,
                *args,
                **kwargs,
            )
        except TypeError:
            continue

    messages.info(
        request,
        "Prescription detail view is not available in this deployment.",
    )
    return redirect("doctor:dashboard")


# =========================================================
# Doctor Diabetes (safe hook)
# =========================================================
def _diabetes_not_available(
    request: HttpRequest,
    patient_id: int,
    *_args,
    **_kwargs,
) -> HttpResponse:
    messages.info(
        request,
        "Diabetes screening page is not enabled yet.",
    )
    return redirect("doctor:patients_list")


def _doctor_diabetes_proxy(
    request: HttpRequest,
    patient_id: int,
    *args,
    **kwargs,
) -> HttpResponse:
    view_function = getattr(
        views,
        "doctor_patient_diabetes_screen",
        None,
    )

    if callable(view_function):
        return view_function(
            request,
            patient_id=patient_id,
            *args,
            **kwargs,
        )

    return _diabetes_not_available(
        request,
        patient_id,
    )


# =========================================================
# Core URL patterns
# =========================================================
urlpatterns = [
    path(
        "",
        RedirectView.as_view(
            pattern_name="doctor:dashboard",
            permanent=False,
        ),
        name="index",
    ),
    path(
        "dashboard/",
        views.doctor_dashboard,
        name="dashboard",
    ),

    # Visit / Consultation
    path(
        VISIT_PATH,
        views.doctor_visit,
        name="visit",
    ),
    path(
        AI_PATH,
        views.visit_ai_assist,
        name="visit_ai_assist",
    ),

    # Aliases (legacy names)
    path(
        VISIT_PATH,
        views.doctor_visit,
        name="doctor_visit",
    ),
    path(
        AI_PATH,
        views.visit_ai_assist,
        name="ai_assist",
    ),

    # Patients
    path(
        PATIENTS_PATH,
        views.patients_list,
        name="patients_list",
    ),
    path(
        PATIENTS_PATH,
        views.patients_list,
        name="patient_list",
    ),
    path(
        "patients/search/",
        views.patient_search,
        name="patient_search",
    ),

    # Doctor diabetes screening/input
    path(
        DOCTOR_DIABETES_PATH,
        _doctor_diabetes_proxy,
        name="patient_diabetes",
    ),
    path(
        DOCTOR_DIABETES_PATH,
        _doctor_diabetes_proxy,
        name="diabetes_screen",
    ),

    # Generate Patient Report: search + page + downloads
    path(
        "patients/reports/search/",
        patient_report_required(
            views.report_search,
        ),
        name="report_search",
    ),
    path(
        "patient/<int:patient_id>/report/",
        patient_report_required(
            views.patient_report,
        ),
        name="patient_report",
    ),
    path(
        "patient/<int:patient_id>/report/pdf/",
        patient_report_required(
            views.report_pdf,
        ),
        name="report_pdf",
    ),
    path(
        "patient/<int:patient_id>/report/csv/",
        patient_report_required(
            views.report_csv,
        ),
        name="report_csv",
    ),

    # Prescription detail alias for templates
    path(
        "prescription/<int:presc_id>/",
        _prescription_detail_proxy,
        name="prescription_detail",
    ),
]


# =========================================================
# Lab routes
# These aliases are protected too, preventing URL bypass.
# =========================================================
if HAS_LAB_VIEWS:
    urlpatterns += [
        path(
            "lab/",
            lab_order_view_required(
                _lab_orders_inbox_proxy,
            ),
            name="lab_orders",
        ),
        path(
            "patient/<int:patient_id>/lab/create/",
            lab_order_add_required(
                _lab_order_create_proxy,
            ),
            name="lab_order_create",
        ),
        path(
            "lab/order/<int:order_id>/",
            lab_order_view_required(
                _lab_order_detail_proxy,
            ),
            name="lab_order_detail",
        ),
        path(
            "lab/<int:order_id>/",
            lab_order_view_required(
                _lab_order_detail_proxy,
            ),
            name="lab_order_detail_legacy",
        ),
    ]
else:
    urlpatterns += [
        path(
            "lab/",
            lab_order_view_required(
                views.doctor_lab_requests,
            ),
            name="lab_orders",
        ),
        path(
            "patient/<int:patient_id>/lab/create/",
            lab_order_add_required(
                _lab_not_available,
            ),
            name="lab_order_create",
        ),
        path(
            "lab/order/<int:order_id>/",
            lab_order_view_required(
                _lab_order_detail_fallback,
            ),
            name="lab_order_detail",
        ),
        path(
            "lab/<int:order_id>/",
            lab_order_view_required(
                _lab_order_detail_fallback,
            ),
            name="lab_order_detail_legacy",
        ),
    ]


# =========================================================
# Reports, analytics, and public doctor routes
# =========================================================
urlpatterns += [
    # Reports & Analytics
    path(
        "reports/",
        analytics_required(
            views.doctor_reports,
        ),
        name="doctor_reports",
    ),
    path(
        "reports/export/",
        analytics_required(
            views.doctor_reports_export,
        ),
        name="doctor_reports_export",
    ),
    path(
        "reports/pdf/",
        analytics_required(
            views.doctor_reports_pdf,
        ),
        name="doctor_reports_pdf",
    ),

    # Available doctors (same path, two names)
    path(
        AVAILABLE_PATH,
        views.available_doctors_list,
        name="available_doctors",
    ),
    path(
        AVAILABLE_PATH,
        views.available_doctors_list,
        name="available",
    ),

    path(
        "profile/<int:pk>/",
        views.doctor_public_profile,
        name="public_profile",
    ),
    path(
        "<int:pk>/",
        views.doctor_detail,
        name="detail",
    ),
]