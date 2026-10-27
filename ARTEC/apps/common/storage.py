from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateFileSystemStorage(FileSystemStorage):
    """Stockage hors de MEDIA/static : aucune URL publique ne peut être générée.
    Les fichiers ne sont servis que par des vues qui contrôlent les permissions."""

    def url(self, name):
        raise ValueError("Les fichiers privés ne sont pas accessibles par URL.")


def get_private_storage():
    return PrivateFileSystemStorage(location=str(settings.PRIVATE_MEDIA_ROOT))
