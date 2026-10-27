from apps.accounts.models import Role


class TechAdminOnlyMixin:
    """L'admin Django (/gestion/) est réservé à l'administrateur technique."""

    def _ok(self, request):
        u = request.user
        return u.is_authenticated and u.is_active and (u.is_superuser or u.role == Role.TECH_ADMIN)

    def has_module_permission(self, request):
        return self._ok(request)

    def has_view_permission(self, request, obj=None):
        return self._ok(request)

    def has_add_permission(self, request):
        return self._ok(request)

    def has_change_permission(self, request, obj=None):
        return self._ok(request)

    def has_delete_permission(self, request, obj=None):
        return self._ok(request)
