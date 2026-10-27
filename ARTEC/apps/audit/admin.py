from django.contrib import admin

from apps.common.admin_mixins import TechAdminOnlyMixin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(TechAdminOnlyMixin, admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "object_type", "object_id")
    list_filter = ("action",)
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
