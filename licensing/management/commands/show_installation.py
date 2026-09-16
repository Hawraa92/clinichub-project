from django.core.management.base import BaseCommand

from licensing.models import Installation


class Command(BaseCommand):
    help = "Show the installation information needed to issue a license."

    def handle(self, *args, **options):
        installation = Installation.get_current()
        self.stdout.write(self.style.SUCCESS("ClinicHub installation"))
        self.stdout.write(f"Installation ID: {installation.pk}")
        self.stdout.write(
            f"Name: {installation.display_name or '(not configured)'}"
        )
        self.stdout.write(
            f"Machine fingerprint: {installation.machine_fingerprint}"
        )
