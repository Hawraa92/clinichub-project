# prescription/models.py
import base64
import logging
import mimetypes
from io import BytesIO

import qrcode

from django.conf import settings
from django.core import signing
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.validators import (
    FileExtensionValidator,
    MinValueValidator,
    MaxValueValidator,
)
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from appointments.models import Appointment
from doctor.models import Doctor

logger = logging.getLogger(__name__)

# Optional PDF engines
try:
    from weasyprint import HTML  # type: ignore
    _HAS_WEASYPRINT = True
except Exception:  # pragma: no cover
    _HAS_WEASYPRINT = False

try:
    from reportlab.pdfgen import canvas  # type: ignore
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    _HAS_REPORTLAB = True
except Exception:  # pragma: no cover
    _HAS_REPORTLAB = False


# =========================
# Upload paths (archived)
# =========================
def _ts(instance):
    return (instance.date_issued or timezone.now())

def pdf_upload_to(instance, filename):
    dt = _ts(instance)
    return f"prescriptions/{dt:%Y/%m}/rx_{getattr(instance, 'pk', 'new')}.pdf"

def qrcode_upload_to(instance, filename):
    dt = _ts(instance)
    return f"qrcodes/{dt:%Y/%m}/qr_{getattr(instance, 'pk', 'new')}.png"

def voice_upload_to(instance, filename):
    dt = _ts(instance)
    return f"voice_notes/{dt:%Y/%m}/{filename}"

def sign_upload_to(instance, filename):
    dt = _ts(instance)
    return f"signatures/{dt:%Y/%m}/{filename}"

def logo_upload_to(instance, filename):
    dt = _ts(instance)
    return f"logos/{dt:%Y/%m}/{filename}"


# =========================
# QuerySet / Manager (RBAC)
# =========================
class PrescriptionQuerySet(models.QuerySet):
    """
    Scopes:
      - doctor   → owns only
      - secretary/admin → all
      - patient  → only their own prescriptions (via appointment.patient.user)
      - others   → none
    """
    def visible_to(self, user):
        role = getattr(user, "role", None)
        if role == "doctor":
            return self.filter(doctor__user=user)
        elif role in {"secretary", "admin"} or getattr(user, "is_superuser", False):
            return self
        elif role == "patient":
            return self.filter(appointment__patient__user=user)
        return self.none()


class PrescriptionManager(models.Manager):
    def get_queryset(self):
        return PrescriptionQuerySet(self.model, using=self._db)

    def visible_to(self, user):
        return self.get_queryset().visible_to(user)


# ==================
# Prescription Model
# ==================
class Prescription(models.Model):
    """
    Doctor's prescription linked to an appointment.
    - Denormalizes patient name and age at issue time.
    - Auto-generates QR (verification URL) and stamps it into a PDF
      that is archived automatically.
    """

    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        verbose_name="Appointment",
        help_text="Related appointment from which patient info is derived",
        db_index=True,
    )
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        verbose_name="Doctor",
        help_text="Doctor who issued this prescription",
        db_index=True,
        related_name="prescriptions",
    )

    # Denormalized patient info from appointment
    patient_full_name = models.CharField(
        max_length=100,
        verbose_name="Patient Name",
        help_text="Snapshot of patient's name at time of prescribing",
    )
    age = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Patient Age",
        help_text="Patient’s age at time of prescribing (auto-calculated if not provided).",
        validators=[MinValueValidator(0), MaxValueValidator(120)],
    )

    # Prescription details
    instructions = models.TextField(
        blank=True,
        null=True,
        verbose_name="Additional Instructions",
    )
    voice_note = models.FileField(
        upload_to=voice_upload_to,
        blank=True,
        null=True,
        verbose_name="Doctor's Voice Note",
        validators=[FileExtensionValidator(["mp3", "wav", "ogg", "m4a"])],
    )
    doctor_signature = models.ImageField(
        upload_to=sign_upload_to,
        blank=True,
        null=True,
        verbose_name="Doctor Signature",
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"])],
    )
    doctor_logo = models.ImageField(
        upload_to=logo_upload_to,
        blank=True,
        null=True,
        verbose_name="Clinic Logo",
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"])],
    )
    pdf_file = models.FileField(
        upload_to=pdf_upload_to,
        blank=True,
        null=True,
        verbose_name="Prescription PDF",
        validators=[FileExtensionValidator(["pdf"])],
    )
    date_issued = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date Issued",
        db_index=True,
    )
    qr_code = models.ImageField(
        upload_to=qrcode_upload_to,
        blank=True,
        null=True,
        verbose_name="QR Code",
        validators=[FileExtensionValidator(["png"])],
    )

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("sent", "Sent"),
        ("completed", "Completed"),
        ("canceled", "Canceled"),
    ]
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="draft",
        verbose_name="Status",
        db_index=True,
    )

    # Manager with visibility helper
    objects = PrescriptionManager()

    class Meta:
        ordering = ["-date_issued"]
        verbose_name = "Prescription"
        verbose_name_plural = "Prescriptions"
        indexes = [
            models.Index(fields=["doctor", "date_issued"]),
            models.Index(fields=["appointment"]),
            models.Index(fields=["status"]),
        ]
        # If you want to forbid more than one prescription per appointment:
        # constraints = [
        #     models.UniqueConstraint(
        #         fields=["appointment"],
        #         name="unique_prescription_per_appointment",
        #     )
        # ]

    # ---------- Convenience properties ----------
    @property
    def doctor_display_name(self) -> str:
        u = getattr(self.doctor, "user", None)
        if not u:
            return "Doctor"
        full = (u.get_full_name() or "").strip()
        if full:
            return full
        if getattr(u, "username", None):
            return u.username
        if getattr(u, "email", None):
            return (u.email or "").split("@")[0]
        return "Doctor"

    @property
    def voice_note_mime(self) -> str:
        if self.voice_note and hasattr(self.voice_note, "name"):
            mime, _ = mimetypes.guess_type(self.voice_note.name)
            return mime or "audio/mpeg"
        return "audio/mpeg"

    # ---------- Denormalization ----------
    def _denormalize_from_appointment(self):
        if not self.appointment_id:
            return
        # Ensure doctor matches appointment's doctor
        self.doctor = self.appointment.doctor

        # Patient name snapshot
        patient = self.appointment.patient
        self.patient_full_name = (
            getattr(patient, "full_name", None)
            or (f"{getattr(patient, 'first_name', '')} {getattr(patient, 'last_name', '')}".strip())
            or getattr(patient, "name", "")
            or self.patient_full_name
        )

        # Compute age if not provided
        if self.age is None:
            dob = getattr(patient, "date_of_birth", None)
            if dob:
                today = timezone.localdate()
                years = (
                    today.year
                    - dob.year
                    - ((today.month, today.day) < (dob.month, dob.day))
                )
                self.age = max(0, min(120, years))

    # ---------- Validation ----------
    def clean(self):
        super().clean()
        # appointment/doctor consistency
        if self.appointment_id and self.doctor_id:
            if self.appointment.doctor_id != self.doctor_id:
                raise models.ValidationError("Doctor must match the appointment's doctor.")

        # patient_full_name cannot be empty if no appointment to denormalize from
        if (self.patient_full_name or "").strip() == "" and not self.appointment_id:
            raise models.ValidationError("Patient name cannot be empty without a related appointment.")

        if self.age is not None and not (0 <= self.age <= 120):
            raise models.ValidationError("Age must be between 0 and 120.")

    # ---------- QR Token / URL (PHI-free payload) ----------
    def make_verification_token(self) -> str:
        """
        Returns a signed token (no PHI) to verify this prescription.
        """
        payload = {"pid": self.pk, "issued": int(self.date_issued.timestamp())}
        return signing.dumps(payload, salt="rx.verify")

    def verification_url(self) -> str:
        site_url = getattr(settings, "SITE_URL", "http://127.0.0.1:8000")
        token = self.make_verification_token()
        return f"{site_url}{reverse('prescription:verify', kwargs={'token': token})}"

    def _qr_png_bytes(self) -> bytes:
        """
        Generate QR PNG bytes for the verification URL (PHI-free).
        """
        try:
            url = self.verification_url()
            qr = qrcode.make(url)
            buf = BytesIO()
            qr.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            logger.error(f"QR code generation failed: {e}")
            return b""

    def generate_qr_code(self):
        """
        Save qr_code field with a PNG that encodes verification URL only.
        """
        data = self._qr_png_bytes()
        if not data:
            return
        filename = f"qr_{self.pk}.png"
        self.qr_code.save(filename, ContentFile(data), save=False)

    # ---------- PDF Generation & Archiving ----------
    def _render_pdf_weasyprint(self) -> bytes:
        """
        Render a simple, branded PDF (HTML → PDF) and stamp the QR as <img>.
        """
        # Inline QR as data: URL
        qr_bytes = self._qr_png_bytes()
        qr_b64 = base64.b64encode(qr_bytes).decode("ascii") if qr_bytes else ""
        meds = "\n".join(
            f"<li>{m.name} — {m.dosage}</li>" for m in self.medications.all()
        )
        issued = timezone.localtime(self.date_issued).strftime("%Y-%m-%d %H:%M")
        html = f"""
        <html>
          <head><meta charset="utf-8"></head>
          <body style="font-family: sans-serif; font-size: 12pt;">
            <h2 style="margin:0;">{self.doctor_display_name}</h2>
            <p style="margin:0;color:#555;">Prescription #{self.pk} — {issued}</p>
            <hr/>
            <h3 style="margin:8px 0 0;">Patient</h3>
            <p style="margin:0;">{self.patient_full_name} — Age: {self.age or ''}</p>
            <h3 style="margin:12px 0 4px;">Medications</h3>
            <ul>{meds or '<li>—</li>'}</ul>
            <h3 style="margin:12px 0 4px;">Instructions</h3>
            <p>{(self.instructions or '').replace('\n','<br/>')}</p>
            <div style="position: absolute; right: 24px; bottom: 24px; text-align:center;">
              <img src="data:image/png;base64,{qr_b64}" width="140"/>
              <div style="font-size:10pt;color:#777;">Scan to verify</div>
            </div>
          </body>
        </html>
        """
        return HTML(string=html).write_pdf()

    def _render_pdf_reportlab(self) -> bytes:
        """
        Fallback PDF rendering using reportlab, with QR stamped.
        """
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        W, H = A4
        x, y = 20 * mm, H - 20 * mm

        def t(line, dx=0, dy=14):
            nonlocal x, y
            y -= dy
            c.drawString(x + dx, y, line)

        issued = timezone.localtime(self.date_issued).strftime("%Y-%m-%d %H:%M")
        c.setFont("Helvetica-Bold", 14)
        t(f"{self.doctor_display_name}", dy=20)
        c.setFont("Helvetica", 10)
        t(f"Prescription #{self.pk} — {issued}", dy=14)
        c.line(x, y-4, W - 20*mm, y-4)

        t("Patient:", dy=22); c.setFont("Helvetica-Bold", 10)
        t(f"{self.patient_full_name} — Age: {self.age or ''}", dy=12); c.setFont("Helvetica", 10)

        t("Medications:", dy=20)
        for m in self.medications.all():
            t(f"• {m.name} — {m.dosage}", dx=10)

        t("Instructions:", dy=20)
        for line in (self.instructions or "—").splitlines():
            t(line, dx=10)

        # Stamp QR at bottom-right
        qr_bytes = self._qr_png_bytes()
        if qr_bytes:
            qbuf = BytesIO(qr_bytes)
            w = h = 40 * mm
            c.drawInlineImage(qbuf, W - w - 20*mm, 20*mm, width=w, height=h)

        c.showPage()
        c.save()
        data = buf.getvalue()
        buf.close()
        return data

    def generate_pdf(self):
        """
        Generate and attach a PDF file that contains the QR code (archived path).
        """
        pdf_bytes = b""
        try:
            if _HAS_WEASYPRINT:
                pdf_bytes = self._render_pdf_weasyprint()
            elif _HAS_REPORTLAB:
                pdf_bytes = self._render_pdf_reportlab()
        except Exception as e:
            logger.error(f"PDF generation failed: {e}")

        if pdf_bytes:
            filename = f"rx_{self.pk}.pdf"
            self.pdf_file.save(filename, ContentFile(pdf_bytes), save=False)

    # ---------- Save Hook ----------
    def save(self, *args, **kwargs):
        """
        On save:
        - Denormalize from appointment (patient name, doctor, age).
        - full_clean() for server-side validation.
        - First save to get PK, then generate QR (PHI-free URL) and PDF, then persist both.
        """
        if self.appointment_id:
            self._denormalize_from_appointment()

        self.full_clean()

        is_new = self.pk is None
        super().save(*args, **kwargs)

        # Generate QR & PDF after first save
        updated_fields = []
        if (is_new or not self.qr_code) and self.pk:
            self.generate_qr_code()
            updated_fields.append("qr_code")
        if (is_new or not self.pdf_file) and self.pk:
            self.generate_pdf()
            updated_fields.append("pdf_file")

        if updated_fields:
            super().save(update_fields=updated_fields)

    # ---------- URLs / String ----------
    def get_absolute_url(self):
        return reverse("prescription:prescription_detail", kwargs={"pk": self.pk})

    def __str__(self):
        return f"Prescription #{self.pk} for {self.patient_full_name}"


# =================
# Medication Model
# =================
class Medication(models.Model):
    """
    Medication entries linked to a Prescription.
    """
    prescription = models.ForeignKey(
        Prescription,
        related_name="medications",
        on_delete=models.CASCADE,
        db_index=True,
    )
    name = models.CharField(
        max_length=200,
        verbose_name="Medication Name",
    )
    dosage = models.CharField(
        max_length=255,
        verbose_name="Dosage",
        help_text="Example: 500 mg — 1 tab PO q8h × 5 days",
    )

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["prescription"]),
        ]

    def clean(self):
        super().clean()
        if not (self.name or "").strip():
            raise models.ValidationError("Medication name cannot be empty.")
        if not (self.dosage or "").strip():
            raise models.ValidationError("Medication dosage cannot be empty.")

    def save(self, *args, **kwargs):
        if self.name:
            self.name = self.name.strip()
        if self.dosage:
            self.dosage = self.dosage.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} — {self.dosage}"
