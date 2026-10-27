from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from apps.common.admin_mixins import TechAdminOnlyMixin

from .models import User


class UserAddForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "full_name", "role", "operator")
        field_classes = {}


class UserEditForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(TechAdminOnlyMixin, BaseUserAdmin):
    form = UserEditForm
    add_form = UserAddForm
    list_display = ("email", "full_name", "role", "operator", "is_active")
    list_filter = ("role", "operator", "is_active")
    search_fields = ("email", "full_name")
    ordering = ("email",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Identité et rôle", {"fields": ("full_name", "role", "operator", "must_change_password")}),
        ("Accès", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "full_name", "role", "operator", "password1", "password2")}),
    )
