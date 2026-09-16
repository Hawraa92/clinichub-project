# appointments/tests/factories.py
from datetime import timedelta

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone
from factory.django import DjangoModelFactory

from appointments.models import (
    Appointment,
    AppointmentStatus,
    PatientBookingRequest,
)
from doctor.models import Doctor
from hospital.models import (
    Branch,
    Department,
    Hospital,
    StaffAssignment,
)
from patient.models import Patient


User = get_user_model()


class HospitalFactory(DjangoModelFactory):
    class Meta:
        model = Hospital
        django_get_or_create = ("code",)

    name = "ClinicHub Test Hospital"
    code = "TEST-HOSPITAL"
    phone = "07700000000"
    email = "hospital-test@example.com"
    address = "Test Hospital Address"
    is_active = True


class BranchFactory(DjangoModelFactory):
    class Meta:
        model = Branch
        django_get_or_create = ("hospital", "code")

    hospital = factory.SubFactory(HospitalFactory)
    name = "Main Test Branch"
    code = "TEST-BRANCH"
    phone = "07700000001"
    email = "branch-test@example.com"
    address = "Test Branch Address"
    is_active = True


class DepartmentFactory(DjangoModelFactory):
    class Meta:
        model = Department
        django_get_or_create = ("branch", "code")

    branch = factory.SubFactory(BranchFactory)
    name = "General Medicine"
    code = "TEST-DEPARTMENT"
    phone_extension = "101"
    is_active = True


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda number: f"user{number}")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.LazyAttribute(
        lambda user: f"{user.username}@example.com"
    )
    role = "secretary"
    password = factory.PostGenerationMethodCall(
        "set_password",
        "testpass123",
    )

    @factory.post_generation
    def create_assignment(self, create, extracted, **kwargs):
        if not create or extracted is False:
            return

        role = getattr(self, "role", None)
        valid_roles = {
            role_value
            for role_value, role_label in StaffAssignment.Roles.choices
        }

        if role not in valid_roles:
            return

        hospital = HospitalFactory()
        branch = BranchFactory(hospital=hospital)
        department = DepartmentFactory(branch=branch)

        StaffAssignment.objects.update_or_create(
            user=self,
            hospital=hospital,
            branch=branch,
            department=department,
            role=role,
            defaults={
                "is_primary": True,
                "is_active": True,
            },
        )


class StaffAssignmentFactory(DjangoModelFactory):
    class Meta:
        model = StaffAssignment

    user = factory.SubFactory(
        UserFactory,
        create_assignment=False,
    )
    hospital = factory.SubFactory(HospitalFactory)
    branch = factory.SubFactory(
        BranchFactory,
        hospital=factory.SelfAttribute("..hospital"),
    )
    department = factory.SubFactory(
        DepartmentFactory,
        branch=factory.SelfAttribute("..branch"),
    )
    role = StaffAssignment.Roles.SECRETARY
    is_primary = True
    is_active = True


class DoctorFactory(DjangoModelFactory):
    class Meta:
        model = Doctor

    user = factory.SubFactory(
        UserFactory,
        role="doctor",
    )


class PatientFactory(DjangoModelFactory):
    class Meta:
        model = Patient

    full_name = factory.Faker("name")


def get_doctor_assignment(doctor):
    assignment = (
        StaffAssignment.objects.filter(
            user=doctor.user,
            role=StaffAssignment.Roles.DOCTOR,
            is_active=True,
        )
        .order_by("-is_primary", "pk")
        .first()
    )

    if assignment is None:
        raise RuntimeError(
            "The doctor does not have an active staff assignment."
        )

    return assignment


class AppointmentFactory(DjangoModelFactory):
    class Meta:
        model = Appointment

    patient = factory.SubFactory(PatientFactory)
    doctor = factory.SubFactory(DoctorFactory)

    hospital = factory.LazyAttribute(
        lambda appointment: get_doctor_assignment(
            appointment.doctor
        ).hospital
    )
    branch = factory.LazyAttribute(
        lambda appointment: get_doctor_assignment(
            appointment.doctor
        ).branch
    )
    department = factory.LazyAttribute(
        lambda appointment: get_doctor_assignment(
            appointment.doctor
        ).department
    )

    scheduled_time = factory.LazyFunction(
        lambda: timezone.now() + timedelta(days=1)
    )
    status = AppointmentStatus.PENDING
    iqd_amount = 0


class PatientBookingRequestFactory(DjangoModelFactory):
    class Meta:
        model = PatientBookingRequest

    full_name = factory.Faker("name")
    contact_info = "07700000002"
    doctor = factory.SubFactory(DoctorFactory)

    hospital = factory.LazyAttribute(
        lambda booking: get_doctor_assignment(
            booking.doctor
        ).hospital
    )
    branch = factory.LazyAttribute(
        lambda booking: get_doctor_assignment(
            booking.doctor
        ).branch
    )
    department = factory.LazyAttribute(
        lambda booking: get_doctor_assignment(
            booking.doctor
        ).department
    )

    scheduled_time = factory.LazyFunction(
        lambda: timezone.now() + timedelta(days=2)
    )
    status = "pending"
    date_of_birth = factory.Faker(
        "date_of_birth",
        minimum_age=18,
        maximum_age=80,
    )