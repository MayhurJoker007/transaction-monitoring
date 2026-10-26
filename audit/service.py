from .models import AuditLog


def record(actor, action, obj, **details):
    """Writes an audit entry. `actor` is a user or None for the system (e.g. the screening worker)."""
    return AuditLog.objects.create(
        actor=actor if getattr(actor, 'is_authenticated', False) else None,
        actor_label=getattr(actor, 'username', None) or 'system',
        action=action,
        object_type=type(obj).__name__,
        object_id=str(obj.pk),
        details=details,
    )
