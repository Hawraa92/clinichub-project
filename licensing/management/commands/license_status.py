from django.core.management.base import BaseCommand

from licensing.models import Installation
from licensing.services import evaluate_license


class Command(BaseCommand):
    help = "Display the current ClinicHub license status."

    def handle(self, *args, **options):
        installation = Installation.get_current()
        status = evaluate_license()

        self.stdout.write(f"Installation ID: {installation.pk}")
        self.stdout.write(f"Status: {status.code}")
        self.stdout.write(f"Allowed: {'yes' if status.allowed else 'no'}")
        self.stdout.write(f"Message: {status.message}")

        if status.license is not None:
            record = status.license
            self.stdout.write(f"License ID: {record.license_id}")
            self.stdout.write(f"Customer: {record.customer_name}")
            self.stdout.write(f"Plan: {record.plan}")
            self.stdout.write(
                f"Expires: {record.expires_at or 'perpetual'}"
            )
            self.stdout.write(
                f"Modules: {', '.join(record.modules) or '(none)'}"
            )

        style = self.style.SUCCESS if status.allowed else self.style.ERROR
        self.stdout.write(style("License is valid." if status.allowed else "License is not valid."))
