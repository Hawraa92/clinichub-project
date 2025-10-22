from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from django.template.defaultfilters import filesizeformat
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils.html import mark_safe
from django.contrib import admin

import uuid
import os
import logging

User = get_user_model()
logger = logging.getLogger(__name__)

def archive_file_path(instance, filename):
    ext = filename.split('.')[-1]
    return f'patient_archives/{instance.archive.pk}/{uuid.uuid4()}.{ext}'

def validate_file_size(value):
    limit_mb = 10
    if value.size > limit_mb * 1024 * 1024:
        raise ValidationError(_("Max file size is %(limit)dMB."), params={'limit': limit_mb})

def validate_file_mimetype(value):
    mime = getattr(value.file, 'content_type', None)
    if not mime:
        import mimetypes
        mime, _unused = mimetypes.guess_type(value.name)
    allowed_mimes = ['application/pdf', 'image/jpeg', 'image/png', 'image/gif']
    if mime not in allowed_mimes:
        raise ValidationError(_("File type not allowed (PDF, JPG, PNG, GIF only)."))

class PatientArchive(models.Model):
    ARCHIVE_TYPES = [
        ('visit', _('Visit')),
        ('lab', _('Lab Result')),
        ('scan', _('Scan')),
        ('prescription', _('Prescription')),
        ('other', _('Other')),
    ]
    STATUS_CHOICES = [
        ('draft', _('Draft')),
        ('final', _('Final')),
        ('cancelled', _('Cancelled')),
    ]
    patient = models.ForeignKey(
        'patient.Patient', on_delete=models.SET_NULL, null=True, related_name='medical_archives'
    )
    doctor = models.ForeignKey(
        'doctor.Doctor', on_delete=models.SET_NULL, null=True, related_name='medical_patient_archives'
    )
    title = models.CharField(max_length=255)
    notes = models.TextField(blank=True)
    archive_type = models.CharField(max_length=50, choices=ARCHIVE_TYPES, default='visit')
    is_critical = models.BooleanField(default=False)
    summary_report = models.TextField(blank=True, help_text=_("Short summary for fast reports"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='final')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name='archives_created'
    )
    updated_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='archives_updated'
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('Patient Archive')
        verbose_name_plural = _('Patient Archives')
        constraints = [
            models.UniqueConstraint(
                fields=['patient', 'doctor', 'title'],
                name='unique_archive_per_patient_doctor'
            )
        ]

    def __str__(self):
        return f"{self.patient.full_name if self.patient else ''} - {self.title} ({self.get_archive_type_display()})"

    def get_color_tag(self):
        color_map = {
            'visit': 'primary',
            'lab': 'success',
            'scan': 'warning',
            'prescription': 'info',
            'other': 'secondary',
        }
        return color_map.get(self.archive_type, 'secondary')

    def get_absolute_url(self):
        return reverse('medical_archive:archive_detail', args=[self.pk])

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # (optional) set updated_by field in your view before saving

class ArchiveAttachment(models.Model):
    archive = models.ForeignKey(
        PatientArchive, on_delete=models.CASCADE, related_name='attachments'
    )
    file = models.FileField(
        upload_to=archive_file_path,
        validators=[
            FileExtensionValidator(['pdf', 'jpg', 'jpeg', 'png', 'gif']),
            validate_file_size,
            validate_file_mimetype
        ]
    )
    description = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='attachments_uploaded'
    )

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = _('Attachment')
        verbose_name_plural = _('Attachments')

    def __str__(self):
        filename = os.path.basename(self.file.name)
        return f"{filename} - {self.description or _('No description')}"

    def is_image(self):
        return self.file.name.lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))

    def is_pdf(self):
        return self.file.name.lower().endswith('.pdf')

    def file_size(self):
        return filesizeformat(self.file.size)

    @admin.display(description=_('Preview'))
    def image_tag(self):
        if self.is_image():
            return mark_safe(f'<img src="{self.file.url}" style="max-height:80px;max-width:80px;" />')
        return "-"

@receiver(post_delete, sender=ArchiveAttachment)
def delete_attachment_file(sender, instance, **kwargs):
    if instance.file and instance.file.name:
        try:
            instance.file.delete(save=False)
            folder = os.path.dirname(instance.file.path)
            if os.path.isdir(folder) and not os.listdir(folder):
                os.rmdir(folder)
        except Exception as e:
            logger.warning(f"Error removing empty archive folder: {e}")
