from django.contrib import admin

from apps.common.admin_mixins import TechAdminOnlyMixin

from .models import Operator


@admin.register(Operator)
class OperatorAdmin(TechAdminOnlyMixin, admin.ModelAdmin):
    list_display = ("name", "code", "status", "contact_email")
    list_filter = ("status",)
    search_fields = ("name", "code")
