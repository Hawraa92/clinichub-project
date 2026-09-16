from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from licensing.crypto import LicenseError
from licensing.services import install_license


class Command(BaseCommand):
    help = "Install and verify a signed ClinicHub license token."

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument(
            "--file",
            dest="license_file",
            help="Path to a UTF-8 text file containing the CHL1 token.",
        )
        source.add_argument(
            "--token",
            dest="license_token",
            help="The complete CHL1 token.",
        )

    def handle(self, *args, **options):
        token = options["license_token"]
        if options["license_file"]:
            try:
                token = Path(options["license_file"]).read_text(
                    encoding="utf-8"
                ).strip()
            except OSError as exc:
                raise CommandError(f"Could not read license file: {exc}") from exc

        try:
            record = install_license(token)
        except LicenseError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"License {record.license_id} activated for "
                f"{record.customer_name}."
            )
        )
