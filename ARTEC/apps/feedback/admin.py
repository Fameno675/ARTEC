from django.contrib import admin

from apps.common.admin_mixins import TechAdminOnlyMixin

from .models import Criterion


@admin.register(Criterion)
class CriterionAdmin(TechAdminOnlyMixin, admin.ModelAdmin):
    list_display = ("position", "code", "label", "category", "is_active")
    list_editable = ("is_active",)
    ordering = ("position",)
