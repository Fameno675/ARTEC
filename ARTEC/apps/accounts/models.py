from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Role(models.TextChoices):
    ARTEC_ADMIN = "artec_admin", "Administrateur ARTEC"
    OPERATOR = "operator", "Compte opérateur"
    TECH_ADMIN = "tech_admin", "Administrateur technique"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, password, **extra):
        if not email:
            raise ValueError("L'e-mail est obligatoire.")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)  # haché (PBKDF2), jamais en clair
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("role", Role.TECH_ADMIN)
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._create(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField("e-mail", unique=True)
    full_name = models.CharField("nom complet", max_length=150)
    role = models.CharField("rôle", max_length=20, choices=Role.choices, default=Role.OPERATOR)
    operator = models.ForeignKey(
        "operators.Operator", null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    is_active = models.BooleanField("actif", default=True)
    is_staff = models.BooleanField("accès admin technique", default=False)
    must_change_password = models.BooleanField("doit changer son mot de passe", default=False)
    created_at = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]
    objects = UserManager()

    class Meta:
        verbose_name = "utilisateur"
        constraints = [
            models.CheckConstraint(
                name="user_operator_iff_operator_role",
                condition=(Q(role="operator", operator__isnull=False) | (~Q(role="operator") & Q(operator__isnull=True))),
            )
        ]

    def __str__(self):
        return self.email

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.role == Role.OPERATOR and not self.operator_id:
            raise ValidationError({"operator": "Un compte opérateur doit être rattaché à un opérateur."})
        if self.role != Role.OPERATOR and self.operator_id:
            raise ValidationError({"operator": "Seuls les comptes opérateurs sont rattachés à un opérateur."})

    @property
    def is_artec_admin(self):
        return self.role == Role.ARTEC_ADMIN

    @property
    def is_operator_user(self):
        return self.role == Role.OPERATOR

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name
