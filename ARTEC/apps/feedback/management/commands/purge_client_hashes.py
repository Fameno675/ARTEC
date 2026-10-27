from django.core.management.base import BaseCommand

from apps.feedback.services import purge_client_hashes


class Command(BaseCommand):
    help = "Efface les pseudonymes techniques (client_hash, device_hash) de plus de 30 jours."

    def handle(self, *args, **options):
        self.stdout.write(f"{purge_client_hashes()} avis purgés.")
