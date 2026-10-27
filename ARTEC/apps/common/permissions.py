from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from apps.accounts.models import Role


def role_required(*roles):
    """Vue privée : anonyme -> connexion ; mauvais rôle -> 403."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not user.is_active or user.role not in roles:
                raise PermissionDenied
            if user.role == Role.OPERATOR and user.operator_id is None:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


operator_required = role_required(Role.OPERATOR)
artec_required = role_required(Role.ARTEC_ADMIN)
