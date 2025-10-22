# accounts/models.py
from django.db import models
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """
    Custom manager using email as the unique login identifier.
    Applies default approval rules based on role.
    """
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """
        Internal helper to create and save a user with the given email and password.
        Expects 'role' in extra_fields (defaults to 'patient').
        """
        if not email:
            raise ValueError(_("The Email field must be set"))

        # Normalize email (defense-in-depth against case-sensitive uniqueness issues)
        email = self.normalize_email(email).strip().lower()

        # Extract role (default to patient)
        role = extra_fields.pop("role", "patient")

        # Default approval rule: patients auto-approved; staff require review
        extra_fields.setdefault("is_approved", True if role == "patient" else False)

        user = self.model(email=email, role=role, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, role="patient", **extra_fields):
        """
        Public user creation; default role=patient.
        """
        extra_fields["role"] = role  # explicit role wins
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        """
        Create a platform superuser (system admin).
        Forces role=admin + full privileges.
        """
        extra_fields.setdefault("role", "admin")
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_approved", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        if extra_fields.get("role") != "admin":
            raise ValueError('Superuser must have role="admin".')

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Primary authentication model.
    - Email is the login ID (unique).
    - Username becomes optional, non-unique, display-only (auto-filled from email if blank).
    - Role controls UI access & workflow approval.
    """
    email = models.EmailField(_("email address"), unique=True, db_index=True)

    # Override AbstractUser.username: make it optional & NOT unique
    username = models.CharField(
        _("username"),
        max_length=150,               # keep 150 to align with defaults/validators if ever reused
        null=True,
        blank=True,
        unique=False,
        help_text=_("Auto-filled from email if left blank"),
    )

    class Roles(models.TextChoices):
        DOCTOR = "doctor", _("Doctor")
        SECRETARY = "secretary", _("Secretary")
        PATIENT = "patient", _("Patient")
        ADMIN = "admin", _("Admin")

    role = models.CharField(
        _("role"),
        max_length=10,
        choices=Roles.choices,
        default=Roles.PATIENT,
        db_index=True,
        help_text=_("Determines which interface the user can access"),
    )

    is_approved = models.BooleanField(
        _("approved"),
        default=False,
        help_text=_("Must be approved by admin before logging in (for doctor/secretary)."),
    )

    # Use email for authentication
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # no extra fields required for createsuperuser

    objects = UserManager()

    def __str__(self):
        return self.get_full_name() or self.email

    def clean(self):
        """
        Normalize email at validation-time too (covers admin forms).
        """
        super().clean()
        if self.email:
            self.email = self.email.strip().lower()

    def save(self, *args, **kwargs):
        # Auto-fill username from email prefix if missing
        if self.email and not self.username:
            self.username = self.email.split("@")[0]
        # Enforce lower-case email consistency again at save
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    # Convenience role checks (handy in templates/decorators)
    @property
    def is_doctor(self):
        return self.role == self.Roles.DOCTOR

    @property
    def is_secretary(self):
        return self.role == self.Roles.SECRETARY

    @property
    def is_patient(self):
        return self.role == self.Roles.PATIENT

    @property
    def is_admin_role(self):
        return self.role == self.Roles.ADMIN
