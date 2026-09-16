from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.models import SoftDeleteModel


class Hospital(SoftDeleteModel):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=30, unique=True)

    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Branch(SoftDeleteModel):
    hospital = models.ForeignKey(
        Hospital,
        on_delete=models.PROTECT,
        related_name="branches",
    )

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=30)

    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["hospital_id", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["hospital", "code"],
                name="unique_branch_code_per_hospital",
            )
        ]

    def __str__(self):
        return f"{self.hospital.name} - {self.name}"


class Department(SoftDeleteModel):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="departments",
    )

    name = models.CharField(max_length=150)
    code = models.CharField(max_length=30)

    phone_extension = models.CharField(max_length=10, blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["branch_id", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "code"],
                name="unique_department_code_per_branch",
            )
        ]

    def __str__(self):
        return f"{self.branch.name} - {self.name}"


class StaffAssignment(SoftDeleteModel):
    class Roles(models.TextChoices):
        HOSPITAL_ADMIN = "hospital_admin", "Hospital Admin"
        DOCTOR = "doctor", "Doctor"
        NURSE = "nurse", "Nurse"
        SECRETARY = "secretary", "Secretary"
        RECEPTIONIST = "receptionist", "Receptionist"
        PHARMACIST = "pharmacist", "Pharmacist"
        LAB_TECHNICIAN = "lab_technician", "Lab Technician"
        RADIOLOGIST = "radiologist", "Radiologist"
        ACCOUNTANT = "accountant", "Accountant"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="hospital_assignments",
    )

    hospital = models.ForeignKey(
        Hospital,
        on_delete=models.PROTECT,
        related_name="staff_assignments",
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="staff_assignments",
        null=True,
        blank=True,
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="staff_assignments",
        null=True,
        blank=True,
    )

    role = models.CharField(
        max_length=30,
        choices=Roles.choices,
        db_index=True,
    )

    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "hospital_id",
            "branch_id",
            "department_id",
            "user_id",
        ]

        indexes = [
            models.Index(
                fields=["user", "hospital", "is_active"],
                name="staff_user_hosp_active_idx",
            ),
            models.Index(
                fields=["hospital", "branch", "department"],
                name="staff_location_idx",
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(
                    is_primary=True,
                    is_deleted=False,
                ),
                name="unique_primary_staff_assignment",
            )
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.branch_id and self.hospital_id:
            if self.branch.hospital_id != self.hospital_id:
                errors["branch"] = (
                    "The selected branch does not belong to this hospital."
                )

        if self.department_id:
            if not self.branch_id:
                errors["branch"] = (
                    "A branch is required when a department is selected."
                )
            elif self.department.branch_id != self.branch_id:
                errors["department"] = (
                    "The selected department does not belong to this branch."
                )

        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                errors["end_date"] = (
                    "The end date cannot be earlier than the start date."
                )

        if self.user_id and self.hospital_id and self.role:
            duplicate_assignment = StaffAssignment.all_objects.filter(
                user_id=self.user_id,
                hospital_id=self.hospital_id,
                branch_id=self.branch_id,
                department_id=self.department_id,
                role=self.role,
                is_deleted=False,
            ).exclude(pk=self.pk)

            if duplicate_assignment.exists():
                errors["user"] = (
                    "This user already has the same assignment in this location."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        user_name = str(self.user) if self.user_id else "Unassigned User"

        location_parts = []

        if self.hospital_id:
            location_parts.append(self.hospital.name)

        if self.branch_id:
            location_parts.append(self.branch.name)

        if self.department_id:
            location_parts.append(self.department.name)

        location = " - ".join(location_parts) or "Unassigned Location"
        role_name = self.get_role_display() if self.role else "Unassigned Role"

        return f"{user_name} | {role_name} | {location}"