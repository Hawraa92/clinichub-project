from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from .access import (
    ecg_form_querysets_for_user,
    filter_ecg_records_for_user,
)
from .forms import ECGFileForm, ECGRecordForm
from .models import ECGRecord


@login_required
def dashboard(request):
    if not request.user.has_perm("ecg.view_ecgrecord"):
        raise PermissionDenied

    records = filter_ecg_records_for_user(
        ECGRecord.objects.select_related(
            "patient",
            "doctor",
            "doctor__user",
            "appointment",
            "hospital",
            "branch",
            "department",
        ),
        request.user,
    )[:10]

    return render(
        request,
        "ecg/dashboard.html",
        {
            "records": records,
            "can_add_record": request.user.has_perm(
                "ecg.add_ecgrecord"
            ),
        },
    )


@login_required
def create_record(request):
    if not request.user.has_perm("ecg.add_ecgrecord"):
        raise PermissionDenied

    form = ECGRecordForm(
        request.POST or None,
        **ecg_form_querysets_for_user(request.user),
    )

    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        record.created_by = request.user
        record.save()

        messages.success(
            request,
            "ECG record created successfully.",
        )

        return redirect(
            "ecg:record_detail",
            record_id=record.pk,
        )

    return render(
        request,
        "ecg/create_record.html",
        {
            "form": form,
        },
    )


@login_required
def record_detail(request, record_id):
    if not request.user.has_perm("ecg.view_ecgrecord"):
        raise PermissionDenied

    queryset = filter_ecg_records_for_user(
        ECGRecord.objects.select_related(
            "patient",
            "doctor",
            "doctor__user",
            "appointment",
            "hospital",
            "branch",
            "department",
            "created_by",
        ).prefetch_related(
            "files",
        ),
        request.user,
    )

    record = get_object_or_404(
        queryset,
        pk=record_id,
    )

    return render(
        request,
        "ecg/record_detail.html",
        {
            "record": record,
            "can_upload_file": (
                request.user.has_perm(
                    "ecg.add_ecgfile"
                )
            ),
        },
    )


@login_required
def upload_file(request, record_id):
    if not request.user.has_perm(
        "ecg.view_ecgrecord"
    ):
        raise PermissionDenied

    if not request.user.has_perm(
        "ecg.add_ecgfile"
    ):
        raise PermissionDenied

    queryset = filter_ecg_records_for_user(
        ECGRecord.objects.select_related(
            "patient",
            "doctor",
            "appointment",
            "hospital",
            "branch",
            "department",
        ),
        request.user,
    )

    record = get_object_or_404(
        queryset,
        pk=record_id,
    )

    form = ECGFileForm(
        request.POST or None,
        request.FILES or None,
    )

    if request.method == "POST" and form.is_valid():
        ecg_file = form.save(
            commit=False
        )

        ecg_file.record = record
        ecg_file.save()

        messages.success(
            request,
            "ECG file uploaded successfully.",
        )

        return redirect(
            "ecg:record_detail",
            record_id=record.pk,
        )

    return render(
        request,
        "ecg/upload_file.html",
        {
            "form": form,
            "record": record,
        },
    )