# prescription/views.py
from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.signing import BadSignature, SignatureExpired, loads
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseForbidden,
)
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

from .models import Prescription

logger = logging.getLogger(__name__)

# =========================
# Helpers / RBAC / Settings
# =========================
def _can_view_prescription(user, p: Prescription) -> bool:
    """
    RBAC:
      - superuser: كل شيء
      - secretary/admin: كل شيء
      - doctor: وصفاته فقط
      - patient: وصفاته (عبر الموعد المرتبط)
    """
    role = getattr(user, "role", None)
    if getattr(user, "is_superuser", False):
        return True
    if role in {"secretary", "admin"}:
        return True
    if role == "doctor":
        return getattr(p.doctor, "user_id", None) == getattr(user, "id", None)
    if role == "patient":
        return getattr(p.appointment.patient, "user_id", None) == getattr(user, "id", None)
    return False


def _verify_max_age_seconds() -> int:
    """مدة صلاحية رمز التحقق (افتراضي: 365 يومًا)."""
    days = int(getattr(settings, "PRESCRIPTION_VERIFY_MAX_AGE_DAYS", 365))
    return max(1, days) * 24 * 60 * 60


def _public_download_enabled() -> bool:
    """هل نُظهر رابط تحميل الـPDF في صفحة التحقق العامة؟ (افتراضي: False)."""
    return bool(getattr(settings, "PRESCRIPTION_PUBLIC_DOWNLOAD", False))


# =========================
#         Private
# =========================
@require_GET
@login_required
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def prescription_detail(request, pk: int) -> HttpResponse:
    """
    صفحة تفصيلية خاصة (تتطلب تسجيل دخول) — قد تعرض PHI.
    """
    p = get_object_or_404(
        Prescription.objects.select_related("doctor__user", "appointment__patient__user"),
        pk=pk,
    )
    if not _can_view_prescription(request.user, p):
        return HttpResponseForbidden("You do not have access to this prescription.")
    return render(request, "prescription/detail.html", {"p": p})


@require_GET
@login_required
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def prescription_pdf(request, pk: int) -> FileResponse:
    """
    تنزيل/عرض PDF (خاص بالمصرّح لهم فقط). يُقدَّم inline.
    """
    p = get_object_or_404(
        Prescription.objects.select_related("doctor__user", "appointment__patient__user"),
        pk=pk,
    )
    if not _can_view_prescription(request.user, p):
        return HttpResponseForbidden("You do not have access to this prescription.")

    if not p.pdf_file:
        raise Http404("PDF not found.")

    resp = FileResponse(p.pdf_file.open("rb"), content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="rx_{p.pk}.pdf"'
    return resp


# =========================
#          Public
# =========================
@require_GET
@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def verify(request, token: str) -> HttpResponse:
    """
    Public verification (بدون تسجيل دخول) — PHI-FREE.
    يثبت صحة الوصفة دون عرض اسم المريض أو بيانات حساسة.
    """
    try:
        data = loads(token, salt="rx.verify", max_age=_verify_max_age_seconds())
        pid = int(data.get("pid"))
    except (BadSignature, SignatureExpired, ValueError, TypeError) as e:
        logger.info("RX verify failed: %s", e)
        return render(
            request,
            "prescription/verify.html",
            {"valid": False, "reason": "Invalid or expired token."},
            status=400,
        )

    p = Prescription.objects.select_related("doctor__user").filter(pk=pid).first()
    if not p:
        return render(
            request,
            "prescription/verify.html",
            {"valid": False, "reason": "Prescription not found."},
            status=404,
        )

    issued_local = timezone.localtime(p.date_issued)
    ctx = {
        "valid": True,
        "rx_id": p.pk,
        "doctor": p.doctor_display_name,
        "issued_at": issued_local.strftime("%Y-%m-%d %H:%M"),
        "status": p.status,  

        "download_url": (p.pdf_file.url if (p.pdf_file and _public_download_enabled()) else None),
    }
    return render(request, "prescription/verify.html", ctx)
