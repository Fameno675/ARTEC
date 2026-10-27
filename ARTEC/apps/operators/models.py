from django.db import models


class OperatorStatus(models.TextChoices):
    ACTIVE = "active", "Actif"
    INACTIVE = "inactive", "Inactif"


class OperatorQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status=OperatorStatus.ACTIVE)


class Operator(models.Model):
    code = models.SlugField(max_length=30, unique=True)
    name = models.CharField("nom", max_length=100, unique=True)
    status = models.CharField("statut", max_length=10, choices=OperatorStatus.choices, default=OperatorStatus.ACTIVE)
    contact_email = models.EmailField("e-mail de contact", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OperatorQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        verbose_name = "opérateur"

    def __str__(self):
        return self.name

    @property
    def is_active(self):
        return self.status == OperatorStatus.ACTIVE
