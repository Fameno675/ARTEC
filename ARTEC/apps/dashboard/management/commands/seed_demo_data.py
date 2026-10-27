"""Données de DÉMONSTRATION, clairement étiquetées (source « DÉMO — données fictives »).

Destinées à vérifier visuellement le frontend. Refuse de s'exécuter hors DEBUG sans --force.
Usage : python manage.py seed_demo_data --yes     |     python manage.py seed_demo_data --purge
"""
import random
from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role, User
from apps.complaints import services as cservices
from apps.datasets.models import DataSource, ImportBatch
from apps.feedback.hashing import content_hash
from apps.feedback.models import Criterion, FeedbackRating, FeedbackSubmission, Source, ValidationStatus
from apps.operators.models import Operator

DEMO_SOURCE = "DÉMO — données fictives"
DEMO_PASSWORD = "Demo-Artec-2026!"
DEMO_USERS = [("demo.artec@example.mg", Role.ARTEC_ADMIN, None), ("demo.orange@example.mg", Role.OPERATOR, "orange"),
              ("demo.yas@example.mg", Role.OPERATOR, "yas"), ("demo.airtel@example.mg", Role.OPERATOR, "airtel")]
BIAS = {"orange": 6.4, "yas": 5.6, "airtel": 5.0}


class Command(BaseCommand):
    help = "Crée ou supprime des données de démonstration étiquetées (jamais en production)."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true")
        parser.add_argument("--purge", action="store_true")
        parser.add_argument("--force", action="store_true", help="autorise hors DEBUG")

    def handle(self, *args, **o):
        if not settings.DEBUG and not o["force"]:
            raise CommandError("Refusé : DEBUG est désactivé (données fictives).")
        if o["purge"]:
            return self.purge()
        if not o["yes"]:
            raise CommandError("Ajoutez --yes pour confirmer la création de données FICTIVES.")
        self.create()

    @transaction.atomic
    def purge(self):
        ds = DataSource.objects.filter(name=DEMO_SOURCE)
        n = FeedbackSubmission.objects.filter(data_source__in=ds).delete()[0]
        ImportBatch.objects.filter(data_source__in=ds).delete()
        ds.delete()
        User.objects.filter(email__in=[e for e, _, _ in DEMO_USERS]).delete()
        self.stdout.write(f"Démo supprimée ({n} objets d'avis). Les réclamations/audits de démo éventuels sont à supprimer à la main.")

    @transaction.atomic
    def create(self):
        rnd = random.Random(2026)
        src, _ = DataSource.objects.get_or_create(name=DEMO_SOURCE, defaults={
            "source_type": "survey_export", "provenance": "DONNÉES FICTIVES générées pour tester l'interface.",
            "usage_limits": "Ne jamais utiliser pour une analyse réelle.", "legal_basis": "Sans objet : données synthétiques."})
        crit = list(Criterion.objects.filter(is_active=True))
        today = date.today()
        subs, ratings = [], []
        volume = {"orange": 140, "yas": 90, "airtel": 22}      # Airtel volontairement sous le seuil d'échantillon
        for code, n in volume.items():
            op = Operator.objects.get(code=code)
            for _ in range(n):
                d = today - timedelta(days=rnd.randint(0, 150))
                scores = {c.code: max(0, min(10, round(rnd.gauss(BIAS[code] + (0.8 if "customer" in c.code else 0), 2.1)))) for c in crit if rnd.random() > .08}
                if not scores:
                    continue
                ch = content_hash(code, d, scores, "external_import") + str(rnd.random())
                s = FeedbackSubmission(operator=op, collected_at=d, source=Source.EXTERNAL_IMPORT, data_source=src, dedup_hash=ch[:64],
                                       content_hash=ch[:64], validation_status=ValidationStatus.ACCEPTED)
                subs.append(s)
                ratings += [FeedbackRating(submission=s, criterion=next(c for c in crit if c.code == k), score=v) for k, v in scores.items()]
        for _ in range(4):   # quelques avis à examiner
            op = Operator.objects.get(code="yas"); d = today - timedelta(days=3)
            s = FeedbackSubmission(operator=op, collected_at=d, source=Source.EXTERNAL_IMPORT, data_source=src, dedup_hash=str(rnd.random())[:30],
                                   validation_status=ValidationStatus.TO_REVIEW, validation_reasons=["all_scores_identical_extreme"])
            subs.append(s); ratings += [FeedbackRating(submission=s, criterion=c, score=10) for c in crit[:5]]
        for k in range(6):   # avis atypiques FICTIFS (notes 0/10 en alternance) : de quoi démontrer l'écran d'examen des alertes ML
            op = Operator.objects.get(code="yas"); d = today - timedelta(days=2 + k % 3)
            s = FeedbackSubmission(operator=op, collected_at=d, source=Source.EXTERNAL_IMPORT, data_source=src,
                                   dedup_hash=f"demo-atypique-{k}", content_hash=f"demo-atypique-{k}", validation_status=ValidationStatus.ACCEPTED)
            subs.append(s); ratings += [FeedbackRating(submission=s, criterion=c, score=(0 if i % 2 else 10)) for i, c in enumerate(crit[:6])]
        FeedbackSubmission.objects.bulk_create(subs)
        FeedbackRating.objects.bulk_create(ratings)
        for email, role, opc in DEMO_USERS:
            if not User.objects.filter(email=email).exists():
                User.objects.create_user(email=email, password=DEMO_PASSWORD, full_name=f"DÉMO {role}", role=role,
                                         operator=Operator.objects.get(code=opc) if opc else None)
        u = User.objects.get(email="demo.orange@example.mg")
        if not u.operator.complaints_filed.exists():
            cservices.create_complaint(user=u, target_operator=Operator.objects.get(code="yas"), subject="[DÉMO] Offre promotionnelle contestée",
                                       description="Réclamation FICTIVE de démonstration : description suffisamment longue pour valider le formulaire.")
        self.stdout.write(self.style.SUCCESS(f"{len(subs)} avis fictifs créés (source « {DEMO_SOURCE} »). Mot de passe des comptes démo : {DEMO_PASSWORD}"))
