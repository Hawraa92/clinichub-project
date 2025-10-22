# appointments/tests/factories.py
import factory
from django.utils import timezone
from django.contrib.auth import get_user_model
from factory.django import DjangoModelFactory

from doctor.models import Doctor
from patient.models import Patient
from appointments.models import (
    Appointment,
    AppointmentStatus,
    PatientBookingRequest
)

User = get_user_model()


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    # sequence يضمن uniqueness للـ username/email
    username = factory.Sequence(lambda n: f"user{n}")
    first_name = factory.Faker("first_name")
    last_name  = factory.Faker("last_name")
    email      = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    role       = "secretary"          # غيّرها في الاستدعاء إذا تحتاج doctor: UserFactory(role="doctor")
    password   = factory.PostGenerationMethodCall("set_password", "testpass123")


class DoctorFactory(DjangoModelFactory):
    class Meta:
        model = Doctor

    # أنشئ User بدور doctor
    user = factory.SubFactory(UserFactory, role="doctor")

    # فقط أضف الحقول الموجودة فعلياً في موديل Doctor
    # إن كانت موجودة أبقها، إن غير موجودة احذفها
    # specialization = factory.Iterator(["Cardiology", "Neurology", "Orthopedics"])
    # department     = factory.Iterator(["cardiology", "neurology", "orthopedics"])


class PatientFactory(DjangoModelFactory):
    class Meta:
        model = Patient

    full_name   = factory.Faker("name")
    # إذا الموديل عنده حقل مثل contact_info بدل contact_phone غيّر السطر
    # contact_info = factory.Faker("phone_number")
    created_at  = factory.LazyFunction(timezone.now)


class AppointmentFactory(DjangoModelFactory):
    class Meta:
        model = Appointment

    patient        = factory.SubFactory(PatientFactory)
    doctor         = factory.SubFactory(DoctorFactory)
    scheduled_time = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(hours=2))
    status         = AppointmentStatus.PENDING
    queue_number   = factory.Sequence(lambda n: n + 1)
    iqd_amount     = 0
    # notes حطها لو عندك حقل
    # notes          = factory.Faker("sentence")


class PatientBookingRequestFactory(DjangoModelFactory):
    class Meta:
        model = PatientBookingRequest

    full_name      = factory.Faker("name")
    contact_info   = factory.Faker("phone_number")
    doctor         = factory.SubFactory(DoctorFactory)
    scheduled_time = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(days=1))
    status         = "pending"
    # الحقول الإجبارية الناقصة:
    date_of_birth  = factory.Faker("date_of_birth", minimum_age=1, maximum_age=80)
    # gender = factory.Iterator(["male", "female"])  # إن وجد
