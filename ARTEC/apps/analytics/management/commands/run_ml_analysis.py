from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from apps.analytics import services
from apps.operators.models import Operator


class Command(BaseCommand):
    help = "Crée et exécute un lot d'analyse ML sur les avis acceptés d'une période."

    def add_arguments(self, parser):
        parser.add_argument("--start", help="AAAA-MM-JJ")
        parser.add_argument("--end", help="AAAA-MM-JJ")
        parser.add_argument("--last-days", type=int, help="fenêtre glissante jusqu'à aujourd'hui (ex. 30) ; à planifier régulièrement")
        parser.add_argument("--operator", help="code opérateur (facultatif)")

    def handle(self, *args, **o):
        if o["last_days"]:
            if o["last_days"] < 1:
                raise CommandError("--last-days doit être >= 1.")
            o["end"], o["start"] = date.today().isoformat(), (date.today() - timedelta(days=o["last_days"] - 1)).isoformat()
        if not (o["start"] and o["end"]):
            raise CommandError("Indiquez --last-days N, ou --start et --end.")
        op = None
        if o["operator"]:
            try:
                op = Operator.objects.get(code=o["operator"])
            except Operator.DoesNotExist:
                raise CommandError("Opérateur inconnu.")
        batch = services.create_batch(requested_by=None, operator=op, start=date.fromisoformat(o["start"]), end=date.fromisoformat(o["end"]))
        batch = services.execute_batch(batch)
        self.stdout.write(f"Lot {batch.id} : {batch.status} ({batch.n_observations} observations) {batch.error_code}")
