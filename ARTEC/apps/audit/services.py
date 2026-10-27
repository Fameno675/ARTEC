from .models import AuditLog


def log(actor, action, obj=None, **metadata):
    """Enregistre une action sensible (import, examen, décision, changement de statut...)."""
    user = actor if (actor is not None and getattr(actor, "is_authenticated", False)) else None
    return AuditLog.objects.create(
        actor=user,
        action=action,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(getattr(obj, "pk", "")) if obj is not None else "",
        metadata=metadata,
    )
