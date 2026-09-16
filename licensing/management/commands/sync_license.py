from django.core.management.base import BaseCommand, CommandError

from licensing.crypto import LicenseError
from licensing.services import synchronize_license


class Command(BaseCommand):
    help = "Synchronize the active license with the optional vendor server."

    def handle(self, *args, **options):
        try:
            record = synchronize_license()
        except LicenseError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"License {record.license_id} synchronized successfully."
            )
        )
