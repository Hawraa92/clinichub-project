from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateArchiveStorage(FileSystemStorage):
    """
    Storage for confidential medical files.

    Files have no public URL and must be served only through
    permission-protected Django views.
    """

    def __init__(self):
        super().__init__(
            location=settings.PRIVATE_MEDIA_ROOT,
            base_url=None,
        )

    def url(self, name):
        raise ValueError(
            "Private medical archive files do not have public URLs."
        )


private_archive_storage = PrivateArchiveStorage()
