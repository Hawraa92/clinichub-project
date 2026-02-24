# medical_archive/tests.py
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse

from doctor.models import Doctor
from patient.models import Patient
from medical_archive.models import PatientArchive, ArchiveAttachment

User = get_user_model()


class MedicalArchiveTests(TestCase):
    def _maybe_set_user_fields(self, user, **fields) -> None:
        """Set optional custom fields (role/is_approved/...) only if they exist."""
        update_fields = []
        for k, v in fields.items():
            if hasattr(user, k):
                setattr(user, k, v)
                update_fields.append(k)
        if update_fields:
            user.save(update_fields=update_fields)

    def _get_or_create_patient(self, user, full_name: str) -> Patient:
        patient, _ = Patient.objects.get_or_create(user=user, defaults={"full_name": full_name})
        if getattr(patient, "full_name", "") != full_name:
            patient.full_name = full_name
            patient.save(update_fields=["full_name"])
        return patient

    def _get_or_create_doctor(self, user, full_name: str, specialty: str) -> Doctor:
        doctor, _ = Doctor.objects.get_or_create(
            user=user,
            defaults={"full_name": full_name, "specialty": specialty},
        )
        dirty = False
        if hasattr(doctor, "full_name") and doctor.full_name != full_name:
            doctor.full_name = full_name
            dirty = True
        if hasattr(doctor, "specialty") and getattr(doctor, "specialty", None) != specialty:
            doctor.specialty = specialty
            dirty = True
        if dirty:
            doctor.save()
        return doctor

    def setUp(self):
        self.doctor_user = User.objects.create_user(email="doc@test.com", password="pass", username="doc")
        self.patient_user = User.objects.create_user(email="pat@test.com", password="pass", username="pat")

        self._maybe_set_user_fields(self.doctor_user, role="doctor", is_approved=True, is_active=True)
        self._maybe_set_user_fields(self.patient_user, role="patient", is_approved=True, is_active=True)

        self.doctor = self._get_or_create_doctor(self.doctor_user, full_name="Dr. Test", specialty="Cardiology")
        self.patient = self._get_or_create_patient(self.patient_user, full_name="Ali Ahmed")

        self.client = Client()
        self.client.force_login(self.doctor_user)

    def test_create_medical_archive(self):
        url = reverse("medical_archive:create_archive")

        count_before = PatientArchive.objects.count()

        data = {
            "patient": self.patient.id,
            "doctor": self.doctor.id,  # حتى لو الفيو يتجاهله
            "title": "Routine Checkup",
            "archive_type": "visit",
            "status": "final",
            "notes": "",
            # ✅ لا ترسل is_critical=False لأن checkbox قد ينقلب True بمجرد وجوده
            # "is_critical": "",
            "summary_report": "",
        }

        response = self.client.post(url, data, follow=False)

        # 1) إذا ردّ 302 → ممتاز غالباً تم الإنشاء + Redirect
        if response.status_code == 302:
            self.assertEqual(PatientArchive.objects.count(), count_before + 1)

        # 2) إذا ردّ 200 → غالباً الفورم بيه أخطاء (لازم نكشفها)
        elif response.status_code == 200:
            # إذا الفيو يرجع context فيه form
            form = getattr(response, "context", None) and response.context.get("form")
            if form is not None:
                self.assertFalse(form.errors, f"Form errors: {form.errors}")
            else:
                # إذا ماكو form بالـ context، نخلي سبب واضح
                self.fail("Create archive returned 200 but no form in context to inspect errors.")
        else:
            self.fail(f"Unexpected status code: {response.status_code}")

        # ✅ تحقق وجود السجل بغض النظر عن doctor لأن بعض الـ views تعيّنه تلقائياً
        self.assertTrue(
            PatientArchive.objects.filter(title="Routine Checkup").exists(),
            "Archive was not created. If status_code was 200, check form errors above.",
        )

    def test_medical_archive_detail_view(self):
        archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Test Visit",
            archive_type="visit",
            status="final",
        )

        url = reverse("medical_archive:archive_detail", kwargs={"archive_id": archive.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Visit")

    def test_medical_archive_list_view(self):
        PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Visit 1",
            archive_type="visit",
            status="final",
        )

        url = reverse("medical_archive:archive_list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visit 1")

    def test_file_attachment_upload(self):
        # ملاحظة: هذا يختبر model-level (مو view upload)
        file_data = SimpleUploadedFile("test2.jpg", b"file_content", content_type="image/jpeg")
        archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="Attachment Test",
            archive_type="visit",
            status="final",
        )

        attachment = ArchiveAttachment.objects.create(
            archive=archive,
            file=file_data,
            description="Test Image",
        )

        self.assertTrue(attachment.is_image())

    def test_str_method(self):
        archive = PatientArchive.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            title="String method test",
            archive_type="visit",
            status="final",
        )
        self.assertIn("String method test", str(archive))
