# medical_archive/test_integration.py
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict
from django.test import Client, TestCase
from django.urls import reverse

from doctor.models import Doctor
from medical_archive.models import ArchiveAttachment, ArchiveVoiceNote, PatientArchive
from patient.models import Patient

User = get_user_model()


class ArchiveIntegrationTest(TestCase):
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
        """
        ✅ عندج Signal يسوي Patient تلقائياً للمستخدم
        لذلك نستخدم get_or_create حتى ما يصير تعارض unique(user).
        """
        patient, _ = Patient.objects.get_or_create(user=user, defaults={"full_name": full_name})
        if getattr(patient, "full_name", "") != full_name:
            patient.full_name = full_name
            patient.save(update_fields=["full_name"])
        return patient

    def _create_doctor_profile(self, user) -> Doctor:
        """
        Create Doctor safely even if Doctor model has optional fields.
        """
        kwargs = {"user": user}
        doctor_field_names = {f.name for f in Doctor._meta.fields}

        if "full_name" in doctor_field_names:
            kwargs["full_name"] = "Dr. Integrate"
        if "specialty" in doctor_field_names:
            kwargs["specialty"] = "Gen"

        return Doctor.objects.create(**kwargs)

    def _url(self, name: str, fallback: str) -> str:
        try:
            return reverse(name)
        except Exception:
            return fallback

    def _assert_not_login_redirect(self, response) -> None:
        """
        إذا صار 302 لازم نتأكد مو Redirect للـ login (يعني auth شغال).
        """
        if response.status_code == 302:
            loc = (response.headers.get("Location") or "").lower()
            self.assertNotIn("login", loc, msg=f"Unexpected login redirect: {loc}")

    def setUp(self):
        # Doctor user
        self.doctor_user = User.objects.create_user(
            email="doc_int@test.com",
            password="pass",
            username="doc_int",
        )
        self._maybe_set_user_fields(self.doctor_user, role="doctor", is_approved=True, is_active=True)
        self.doctor = self._create_doctor_profile(self.doctor_user)

        # Patient user
        self.patient_user = User.objects.create_user(
            email="pat_int@test.com",
            password="pass",
            username="pat_int",
        )
        self._maybe_set_user_fields(self.patient_user, role="patient", is_approved=True, is_active=True)
        self.patient = self._get_or_create_patient(self.patient_user, "Ali Integrate")

        self.client = Client()
        # ✅ force_login أقوى من login بالتستات
        self.client.force_login(self.doctor_user)

    def test_create_archive_via_view_with_attachment(self):
        url = self._url("medical_archive:create_archive", "/archive/create/")

        file_data = SimpleUploadedFile(
            "integrate.pdf",
            b"123456",
            content_type="application/pdf",
        )

        data = {
            "patient": str(self.patient.id),
            "title": "Integration Archive",
            "archive_type": "visit",
            "status": "final",
            "description": "Test",
            # ✅ حسب مشروعج الحقل اسمه غالباً "files"
            "files": file_data,
        }

        response = self.client.post(url, data=data, follow=False)
        self._assert_not_login_redirect(response)

        # نجاح غالباً PRG -> 302
        self.assertEqual(response.status_code, 302)

        self.assertTrue(PatientArchive.objects.filter(title="Integration Archive").exists())
        # بعض المشاريع ممكن تخزن أكثر من ملف/أو تختلف آلية الربط، فخليها >= 1
        self.assertGreaterEqual(ArchiveAttachment.objects.count(), 1)

    def test_voice_title_without_audio_should_fail(self):
        """
        ✅ هذا التست يركز على شيء ثابت:
        حتى لو صار redirect أو 200، لازم ما ينحفظ VoiceNote بدون ملف صوت.
        وبالنسبة للأرشيف:
        - إذا الڤيو يعتبر الطلب Valid -> 302 وقد ينحفظ Archive
        - إذا يعتبره Invalid -> 200 وما ينحفظ Archive
        """

        url = self._url("medical_archive:create_archive", "/archive/create/")

        # emulate the "two title fields named title" collision
        post = QueryDict("", mutable=True)
        post["patient"] = str(self.patient.id)
        post["archive_type"] = "visit"
        post["status"] = "final"
        post["description"] = "Test"

        # title[0] = archive title, title[1] = voice title (مثل ما يصير بالقالب)
        post.setlist("title", ["Archive With Voice Title", "Voice Title Only"])

        response = self.client.post(url, data=post, follow=False)
        self._assert_not_login_redirect(response)

        # بعض implementations ترجع 200 (errors)، وبعضها 302 (PRG)
        self.assertIn(response.status_code, (200, 302))

        # ✅ الثابت: ماكو صوت مرفوع => لازم ما ينحفظ VoiceNote
        self.assertEqual(ArchiveVoiceNote.objects.count(), 0)

        # ✅ السلوك المتوقَّع للأرشيف حسب نوع الاستجابة
        if response.status_code == 302:
            # غالباً archive انحفظ
            self.assertEqual(PatientArchive.objects.count(), 1)
        else:
            # 200 يعني فشل validation => ما ينحفظ شي
            self.assertEqual(PatientArchive.objects.count(), 0)