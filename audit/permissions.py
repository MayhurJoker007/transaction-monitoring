from rest_framework.permissions import BasePermission


def has_role(user, *roles):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=roles).exists()


def role_required(*roles):
    """Permission class factory: role_required('analyst', 'supervisor')."""

    class HasRole(BasePermission):
        message = 'requires one of these roles: %s' % ', '.join(roles)

        def has_permission(self, request, view):
            return has_role(request.user, *roles)

    HasRole.__name__ = 'HasRole_' + '_'.join(roles)
    return HasRole
