from __future__ import annotations

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateClinicalStorage(FileSystemStorage):
    """Private storage for clinical files with no public URL."""

    def __init__(self):
        super().__init__(location=None, base_url=None)

    @property
    def base_location(self):
        return settings.PRIVATE_MEDIA_ROOT

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        raise ValueError("Private clinical files do not have public URLs.")


private_clinical_storage = PrivateClinicalStorage()
