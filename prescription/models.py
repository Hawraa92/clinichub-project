# prescription/models.py
from __future__ import annotations

import base64
import logging
import mimetypes
from datetime import datetime
from io import BytesIO

import qrcode
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from appointments.models import Appointment
from doctor.models import Doctor
from patient.models import Patient  # ✅ direct patient link

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
    from reportlab.lib.utils import ImageReader  # type: ignore

    _HAS_REPORTLAB = True
except Exception:  # pragma: no cover
    _HAS_REPORTLAB = False


# =========================
# Settings / constants
# =========================
VOICE_NOTE_ALLOWED_EXTENSIONS = ["mp3", "wav", "ogg", "m4a", "webm"]


def _secretary_can_view() -> bool:
    # افتراضي: False (حسب تفضيلج السابق "الطبيب فقط")
    return bool(getattr(settings, "PRESCRIPTION_SECRETARY_CAN_VIEW", False))


def _admin_can_view() -> bool:
    # افتراضي: True (عدليها إذا تريدين تمنعين الأدمن أيضاً)
    return bool(getattr(settings, "PRESCRIPTION_ADMIN_CAN_VIEW", True))


# =========================
# Upload paths
# =========================
def _ts(instance) -> datetime:
    return getattr(instance, "date_issued", None) or timezone.now()


def pdf_upload_to(instance, filename: str) -> str:
    dt = _ts(instance)
    return f"prescriptions/{dt:%Y/%m}/rx_{getattr(instance, 'pk', 'new')}.pdf"


def qrcode_upload_to(instance, filename: str) -> str:
    dt = _ts(instance)
    return f"qrcodes/{dt:%Y/%m}/qr_{getattr(instance, 'pk', 'new')}.png"


def voice_upload_to(instance, filename: str) -> str:
    dt = _ts(instance)
    return f"voice_notes/{dt:%Y/%m}/{filename}"


def sign_upload_to(instance, filename: str) -> str:
    dt = _ts(instance)
    return f"signatures/{dt:%Y/%m}/{filename}"


def logo_upload_to(instance, filename: str) -> str:
    dt = _ts(instance)
    return f"logos/{dt:%Y/%m}/{filename}"


# =========================
# Utilities (model field helpers)
# =========================
def _model_has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


def _doctor_specialty_value(doc: Doctor) -> str:
    """
    Resolve specialty from different possible field names safely.
    """
    for f in ("specialty", "speciality", "specialization", "department"):
        if hasattr(doc, f):
            v = getattr(doc, f, None) or ""
            v = str(v).strip()
            if v:
                return v
    return ""


def _file_to_data_uri(file_field) -> str:
    """
    Convert ImageField/FileField to data URI (best for WeasyPrint to render locally).
    """
    if not file_field:
        return ""
    try:
        name = getattr(file_field, "name", None) or ""
        mime, _ = mimetypes.guess_type(name)
        mime = mime or "application/octet-stream"

        try:
            file_field.open("rb")
        except Exception:
            pass

        data = file_field.read()
        if not data:
            return ""

        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return ""


# =========================
# QuerySet / Manager (RBAC)
# =========================
class PrescriptionQuerySet(models.QuerySet):
    """
    Scopes:
      - superuser → all
      - doctor   → owns only
      - secretary/admin → optional via settings
      - patient  → only their own prescriptions
      - others   → none
    """

    def visible_to(self, user):
        if not user or not getattr(user, "is_authenticated", False):
            return self.none()

        if getattr(user, "is_superuser", False):
            return self

        role = (getattr(user, "role", None) or "").lower()

        if role == "doctor":
            return self.filter(doctor__user=user)

        if role == "secretary":
            return self if _secretary_can_view() else self.none()

        if role == "admin":
            return self if _admin_can_view() else self.none()

        if role == "patient":
            return self.filter(
                models.Q(patient__user=user) | models.Q(appointment__patient__user=user)
            )

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
    - Auto-generates QR (verification URL) safely (PHI-free).
    - PDF generated when medications exist OR when explicitly requested.
    """

    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        verbose_name="Appointment",
        help_text="Related appointment from which patient info is derived",
        db_index=True,
    )

    # ✅ direct patient link (helps queries/reports)
    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="Patient",
        help_text="Direct link to patient (auto-filled from appointment)",
        db_index=True,
        related_name="prescriptions",
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

    # Dx (اختياري)
    diagnosis = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Diagnosis (Dx)",
        help_text="Optional. Example: sore throat, fever, pelvic pain ...",
        db_index=True,
    )

    template_key = models.CharField(
        max_length=50,
        blank=True,
        default="default",
        verbose_name="Template Key",
        help_text="UI template identifier (e.g., dermatology, cardiology).",
        db_index=True,
    )

    instructions = models.TextField(
        blank=True,
        null=True,
        verbose_name="Additional Instructions",
    )

    # ✅ FIX: add webm because browser recorder غالبًا يطلع WebM
    voice_note = models.FileField(
        upload_to=voice_upload_to,
        blank=True,
        null=True,
        verbose_name="Doctor's Voice Note",
        validators=[FileExtensionValidator(VOICE_NOTE_ALLOWED_EXTENSIONS)],
        help_text="Allowed formats: mp3, wav, ogg, m4a, webm",
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

    objects = PrescriptionManager()

    class Meta:
        ordering = ["-date_issued"]
        verbose_name = "Prescription"
        verbose_name_plural = "Prescriptions"
        indexes = [
            models.Index(fields=["doctor", "date_issued"]),
            models.Index(fields=["patient", "date_issued"]),
            models.Index(fields=["appointment"]),
            models.Index(fields=["status"]),
            models.Index(fields=["template_key"]),
            models.Index(fields=["diagnosis"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["appointment"],
                name="unique_prescription_per_appointment",
            )
        ]

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
            return mime or "audio/webm"
        return "audio/webm"

    @property
    def effective_logo(self):
        if self.doctor_logo:
            return self.doctor_logo
        return getattr(self.doctor, "clinic_logo", None)

    @property
    def effective_signature(self):
        if self.doctor_signature:
            return self.doctor_signature
        return getattr(self.doctor, "signature", None)

    # ---------- Denormalization ----------
    def _denormalize_from_appointment(self) -> None:
        if not self.appointment_id:
            return

        # Ensure doctor matches appointment's doctor
        self.doctor = self.appointment.doctor

        patient = self.appointment.patient
        self.patient = patient  # ✅ direct patient link

        name = (
            (getattr(patient, "full_name", None) or "").strip()
            or f"{getattr(patient, 'first_name', '')} {getattr(patient, 'last_name', '')}".strip()
            or (getattr(patient, "name", "") or "").strip()
        )
        self.patient_full_name = name or (self.patient_full_name or "").strip() or "Unknown Patient"

        # Compute age if not provided
        if self.age is None:
            direct_age = getattr(patient, "age", None)
            if direct_age is not None:
                try:
                    self.age = int(direct_age)
                except Exception:
                    self.age = None

            if self.age is None:
                dob = getattr(patient, "date_of_birth", None)
                if dob:
                    today = timezone.localdate()
                    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                    self.age = max(0, min(120, years))

        # template_key default from doctor specialty (robust)
        if not (self.template_key or "").strip():
            spec = _doctor_specialty_value(self.doctor).lower()
            self.template_key = spec or "default"

    # ---------- Validation ----------
    def clean(self):
        super().clean()

        if self.appointment_id and self.doctor_id:
            if self.appointment.doctor_id != self.doctor_id:
                raise ValidationError("Doctor must match the appointment's doctor.")

        if self.appointment_id and self.patient_id:
            if self.appointment.patient_id != self.patient_id:
                raise ValidationError("Patient must match the appointment's patient.")

        if (self.patient_full_name or "").strip() == "":
            raise ValidationError("Patient name cannot be empty.")

        if self.age is not None and not (0 <= self.age <= 120):
            raise ValidationError("Age must be between 0 and 120.")

        if self.diagnosis is not None:
            d = (self.diagnosis or "").strip()
            self.diagnosis = d or None

        if (self.template_key or "").strip() == "":
            self.template_key = "default"

    # ---------- QR Token / URL (PHI-free payload) ----------
    def make_verification_token(self) -> str:
        if not self.pk:
            raise ValidationError("Cannot create token for unsaved prescription.")

        issued_ts = int((self.date_issued or timezone.now()).timestamp())
        payload = {"pid": self.pk, "issued": issued_ts}
        return signing.dumps(payload, salt="rx.verify")

    def verification_url(self) -> str:
        """
        IMPORTANT:
        - الأفضل بالـ urls.py يكون verify/<path:token>/ حتى ما ينكسر التوكن.
        """
        site_url = getattr(settings, "SITE_URL", "http://127.0.0.1:8000").rstrip("/")
        token = self.make_verification_token()
        return f"{site_url}{reverse('prescription:verify', kwargs={'token': token})}"

    def _qr_png_bytes(self) -> bytes:
        try:
            url = self.verification_url()
            qr = qrcode.QRCode(
                version=1,
                box_size=6,
                border=2,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            logger.error("QR code generation failed: %s", e)
            return b""

    def generate_qr_code(self) -> None:
        data = self._qr_png_bytes()
        if not data:
            return

        filename = f"qr_{self.pk}.png"
        self.qr_code.save(filename, ContentFile(data), save=False)

    # ---------- PDF Generation ----------
    def _render_pdf_weasyprint(self) -> bytes:
        qr_bytes = self._qr_png_bytes()
        qr_b64 = base64.b64encode(qr_bytes).decode("ascii") if qr_bytes else ""

        def esc(s: str) -> str:
            return escape(s or "")

        meds_items = [f"<li>{esc(m.name)} — {esc(m.dosage)}</li>" for m in self.medications.all()]
        meds = "\n".join(meds_items) or "<li>—</li>"

        issued_dt = self.date_issued or timezone.now()
        if getattr(settings, "USE_TZ", True):
            try:
                issued_dt = timezone.localtime(issued_dt)
            except Exception:
                pass
        issued = issued_dt.strftime("%Y-%m-%d %H:%M")

        instr = esc(self.instructions or "").replace("\n", "<br/>")

        dx_html = ""
        if (self.diagnosis or "").strip():
            dx = esc(self.diagnosis).replace("\n", "<br/>")
            dx_html = f"<p style='margin:6px 0 0;'><b>Dx:</b> {dx}</p>"

        logo_uri = _file_to_data_uri(self.effective_logo)
        sig_uri = _file_to_data_uri(self.effective_signature)

        logo_tag = (
            f'<img src="{logo_uri}" style="height:42px;vertical-align:middle;margin-right:10px;" />'
            if logo_uri
            else ""
        )
        sig_tag = f'<img src="{sig_uri}" style="height:60px;" />' if sig_uri else ""

        html = f"""
        <html>
          <head><meta charset="utf-8"></head>
          <body style="font-family: sans-serif; font-size: 12pt; margin: 18mm;">
            <div style="display:flex;align-items:center;gap:10px;">
              {logo_tag}
              <div>
                <h2 style="margin:0;">{esc(self.doctor_display_name)}</h2>
                <p style="margin:0;color:#555;">Prescription #{self.pk} — {esc(issued)}</p>
              </div>
            </div>
            <hr/>

            <h3 style="margin:8px 0 0;">Patient</h3>
            <p style="margin:0;">{esc(self.patient_full_name)} — Age: {self.age or ''}</p>
            {dx_html}

            <h3 style="margin:12px 0 4px;">Medications</h3>
            <ul>{meds}</ul>

            <h3 style="margin:12px 0 4px;">Instructions</h3>
            <p>{instr or "—"}</p>

            <div style="margin-top:18px;">
              <div style="color:#777;font-size:10pt;">Doctor Signature</div>
              {sig_tag or "<div style='color:#999;'>—</div>"}
            </div>

            <div style="position: fixed; right: 18mm; bottom: 18mm; text-align:center;">
              <img src="data:image/png;base64,{qr_b64}" width="140" />
              <div style="font-size:10pt;color:#777;">Scan to verify</div>
            </div>
          </body>
        </html>
        """
        return HTML(string=html).write_pdf()

    def _render_pdf_reportlab(self) -> bytes:
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        w_page, h_page = A4
        x, y = 20 * mm, h_page - 20 * mm

        def t(line: str, dx=0, dy=14):
            nonlocal y
            y -= dy
            c.drawString(x + dx, y, line)

        issued_dt = self.date_issued or timezone.now()
        try:
            if getattr(settings, "USE_TZ", True):
                issued_dt = timezone.localtime(issued_dt)
        except Exception:
            pass
        issued = issued_dt.strftime("%Y-%m-%d %H:%M")

        c.setFont("Helvetica-Bold", 14)
        t(f"{self.doctor_display_name}", dy=20)

        c.setFont("Helvetica", 10)
        t(f"Prescription #{self.pk} — {issued}", dy=14)
        c.line(x, y - 4, w_page - 20 * mm, y - 4)

        t("Patient:", dy=22)
        c.setFont("Helvetica-Bold", 10)
        t(f"{self.patient_full_name} — Age: {self.age or ''}", dy=12)

        if (self.diagnosis or "").strip():
            c.setFont("Helvetica", 10)
            t("Dx:", dy=14)
            dx_lines = (self.diagnosis or "").splitlines() or [self.diagnosis]
            for line in dx_lines:
                t(f"{line}", dx=10, dy=12)

        c.setFont("Helvetica", 10)

        t("Medications:", dy=20)
        meds = list(self.medications.all())
        if meds:
            for m in meds:
                t(f"• {m.name} — {m.dosage}", dx=10)
        else:
            t("• —", dx=10)

        t("Instructions:", dy=20)
        lines = (self.instructions or "—").splitlines() or ["—"]
        for line in lines:
            t(line, dx=10)

        qr_bytes = self._qr_png_bytes()
        if qr_bytes:
            try:
                img = ImageReader(BytesIO(qr_bytes))
                img_w = img_h = 40 * mm
                c.drawImage(
                    img,
                    w_page - img_w - 20 * mm,
                    20 * mm,
                    width=img_w,
                    height=img_h,
                    preserveAspectRatio=True,
                    mask="auto",
                )
            except Exception as e:
                logger.warning("ReportLab QR stamp failed: %s", e)

        c.showPage()
        c.save()
        data = buf.getvalue()
        buf.close()
        return data

    def generate_pdf(self) -> None:
        if not self.pk:
            raise ValidationError("Cannot generate PDF for unsaved prescription.")

        pdf_bytes = b""
        try:
            if _HAS_WEASYPRINT:
                pdf_bytes = self._render_pdf_weasyprint()
            elif _HAS_REPORTLAB:
                pdf_bytes = self._render_pdf_reportlab()
            else:
                logger.warning("No PDF engine available (weasyprint/reportlab).")
        except Exception as e:
            logger.error("PDF generation failed: %s", e)

        if pdf_bytes:
            filename = f"rx_{self.pk}.pdf"
            self.pdf_file.save(filename, ContentFile(pdf_bytes), save=False)

    def regenerate_assets(self, *, force_qr: bool = False, force_pdf: bool = False) -> None:
        if not self.pk:
            raise ValidationError("Cannot regenerate assets for unsaved prescription.")

        if force_qr or not self.qr_code:
            self.generate_qr_code()

        try:
            has_meds = self.medications.exists()
        except Exception:
            has_meds = False

        if (force_pdf or not self.pdf_file) and has_meds:
            self.generate_pdf()

    # ---------- Save Hook ----------
    def save(self, *args, **kwargs):
        if self.appointment_id:
            self._denormalize_from_appointment()

        self.full_clean()

        is_new = self.pk is None
        super().save(*args, **kwargs)

        updated_fields: list[str] = []

        if (is_new or not self.qr_code) and self.pk:
            self.generate_qr_code()
            updated_fields.append("qr_code")

        try:
            has_meds = bool(self.pk and self.medications.exists())
        except Exception:
            has_meds = False

        # لا تولّد PDF لحظة الإنشاء إذا ماكو أدوية بعد
        if self.pk and (not self.pdf_file) and has_meds and (not is_new):
            self.generate_pdf()
            if self.pdf_file:
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
    prescription = models.ForeignKey(
        Prescription,
        related_name="medications",
        on_delete=models.CASCADE,
        db_index=True,
    )

    name = models.CharField(max_length=200, verbose_name="Medication Name")
    dosage = models.CharField(
        max_length=255,
        verbose_name="Dosage",
        help_text="Example: 500 mg — 1 tab PO q8h × 5 days",
    )

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["prescription"])]

    def clean(self):
        super().clean()
        if not (self.name or "").strip():
            raise ValidationError("Medication name cannot be empty.")
        if not (self.dosage or "").strip():
            raise ValidationError("Medication dosage cannot be empty.")

    def save(self, *args, **kwargs):
        if self.name:
            self.name = self.name.strip()
        if self.dosage:
            self.dosage = self.dosage.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} — {self.dosage}"