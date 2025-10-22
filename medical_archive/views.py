from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, FileResponse

from .models import PatientArchive, ArchiveAttachment
from .forms import PatientArchiveForm, ArchiveAttachmentForm
from doctor.models import Doctor

def _is_authorized_for_archive(user, archive):
    """
    هل المستخدم يحق له الوصول لهذا الأرشيف؟
    الطبيب الخاص أو المريض نفسه فقط.
    """
    if not user.is_authenticated:
        return False
    if archive.doctor and archive.doctor.user_id == user.id:
        return True
    if archive.patient and archive.patient.user_id == user.id:
        return True
    return False

@login_required
def archive_list(request):
    """
    عرض أرشيفات المريض أو الطبيب حسب الصلاحية، مع دعم البحث والتصفية.
    """
    user = request.user
    archives = PatientArchive.objects.select_related('patient', 'doctor', 'doctor__user').order_by('-created_at')

    # تصفية حسب صلاحية المستخدم
    if any([hasattr(user, "doctor_profile"), hasattr(user, "doctor")]):
        archives = archives.filter(doctor__user=user)
    elif any([hasattr(user, "patient_profile"), hasattr(user, "patient")]):
        archives = archives.filter(patient__user=user)
    else:
        archives = archives.none()

    selected_type = request.GET.get('type', '')
    selected_doctor = request.GET.get('doctor', '')
    search = request.GET.get('search', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')

    if selected_type:
        archives = archives.filter(archive_type=selected_type)
    if selected_doctor:
        archives = archives.filter(doctor_id=selected_doctor)
    if search:
        archives = archives.filter(
            Q(patient__full_name__icontains=search) |
            Q(title__icontains=search)
        )
    if start_date:
        archives = archives.filter(created_at__date__gte=start_date)
    if end_date:
        archives = archives.filter(created_at__date__lte=end_date)

    paginator = Paginator(archives, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    types = PatientArchive.ARCHIVE_TYPES
    doctors = [(doc.id, doc.user.get_full_name()) for doc in Doctor.objects.all()]

    return render(request, 'medical_archive/archive_list.html', {
        'page_obj': page_obj,
        'types': types,
        'doctors': doctors,
        'selected_type': selected_type,
        'selected_doctor': selected_doctor,
    })

@login_required
def create_archive(request):
    """
    إنشاء أرشيف جديد مع مرفقات.
    """
    if request.method == 'POST':
        archive_form = PatientArchiveForm(request.POST)
        attachment_form = ArchiveAttachmentForm(request.POST, request.FILES)

        forms_valid = archive_form.is_valid() and attachment_form.is_valid()

        if not forms_valid:
            if not archive_form.is_valid():
                messages.error(request, "❌ Please check the archive form fields.")
            if not attachment_form.is_valid():
                for error in attachment_form.errors.get('files', []):
                    messages.error(request, f"📎 {error}")
                messages.error(request, "❌ Please review the attachments.")

        if forms_valid:
            archive = archive_form.save(commit=False)
            archive.created_by = request.user
            archive.save()

            files = request.FILES.getlist('files')
            description = attachment_form.cleaned_data.get('description', '')

            for file in files:
                ArchiveAttachment.objects.create(
                    archive=archive,
                    file=file,
                    description=description
                )

            messages.success(request, "✅ Archive and attachments saved successfully.")
            return redirect('medical_archive:archive_list')

    else:
        archive_form = PatientArchiveForm()
        attachment_form = ArchiveAttachmentForm()

    return render(request, 'medical_archive/create_archive.html', {
        'archive_form': archive_form,
        'attachment_form': attachment_form,
    })

@login_required
def archive_detail(request, archive_id):
    """
    عرض تفاصيل أرشيف معيّن مع الحماية.
    """
    archive = get_object_or_404(PatientArchive, pk=archive_id)
    if not _is_authorized_for_archive(request.user, archive):
        raise Http404("Not found.")

    attachments = archive.attachments.all()
    if not attachments.exists():
        messages.info(request, "ℹ️ No attachments found for this archive.")

    return render(request, 'medical_archive/archive_detail.html', {
        'archive': archive,
        'attachments': attachments,
    })

@login_required
def edit_archive(request, archive_id):
    """
    تعديل الأرشيف (يحمي من غير المصرّح).
    """
    archive = get_object_or_404(PatientArchive, pk=archive_id)
    if not _is_authorized_for_archive(request.user, archive):
        raise Http404("Not found.")

    if request.method == 'POST':
        form = PatientArchiveForm(request.POST, instance=archive)
        if form.is_valid():
            form.save()
            messages.success(request, "✅ Archive updated successfully.")
            return redirect('medical_archive:archive_detail', archive.id)
        else:
            messages.error(request, "❌ Please correct the errors below.")
    else:
        form = PatientArchiveForm(instance=archive)

    return render(request, 'medical_archive/edit_archive.html', {
        'form': form,
        'archive': archive,
    })

@login_required
def delete_archive(request, archive_id):
    """
    حذف الأرشيف والمرفقات (مع حماية صلاحية الحذف).
    """
    archive = get_object_or_404(PatientArchive, pk=archive_id)
    if not _is_authorized_for_archive(request.user, archive):
        raise Http404("Not found.")

    if request.method == 'POST':
        archive.attachments.all().delete()
        archive.delete()
        messages.success(request, "🗑️ Archive and all attachments deleted.")
        return redirect('medical_archive:archive_list')

    return render(request, 'medical_archive/delete_archive.html', {
        'archive': archive,
    })

@login_required
def download_attachment(request, attachment_id):
    """
    تحميل مرفق (مع حماية الوصول).
    """
    attachment = get_object_or_404(ArchiveAttachment, pk=attachment_id)
    archive = attachment.archive
    if not _is_authorized_for_archive(request.user, archive):
        raise Http404("Not allowed")
    return FileResponse(attachment.file.open("rb"), as_attachment=True, filename=attachment.file.name)
