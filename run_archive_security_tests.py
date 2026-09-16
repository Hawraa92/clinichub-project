import os
import tempfile
from pathlib import Path

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "ClinicHub.settings",
)

import django
django.setup()

from django.core.management import call_command
from medical_archive.storage import private_archive_storage


with tempfile.TemporaryDirectory(
    prefix="clinichub_archive_tests_",
    ignore_cleanup_errors=True,
) as temp_dir:

    private_archive_storage._location = Path(temp_dir)

    for cached_name in (
        "base_location",
        "location",
    ):
        private_archive_storage.__dict__.pop(
            cached_name,
            None,
        )

    print("Temporary test storage:", temp_dir)

    call_command(
        "test",
        "medical_archive.test_file_security",
        "medical_archive.test_location_precedence",
        verbosity=1,
    )
