from functools import wraps

from django.core.exceptions import PermissionDenied


GLOBAL_ROLES = frozenset({"ADMIN", "SUPERVISOR", "AUDITOR"})

def user_has_role(user, allowed_roles):
    return bool(
        user.is_authenticated
        and (
            user.is_superuser
            or getattr(user, "role", None) in allowed_roles
        )
    )


def roles_required(*allowed_roles):
    allowed = frozenset(allowed_roles)

    def decorator(view_function):
        @wraps(view_function)
        def wrapped(request, *args, **kwargs):
            if not user_has_role(request.user, allowed):
                raise PermissionDenied("No tiene permisos para acceder a este módulo.")
            return view_function(request, *args, **kwargs)

        return wrapped

    return decorator

DELIVERY_MANAGEMENT_ROLES = frozenset({"ADMIN", "SUPERVISOR"})


def can_manage_deliveries(user):
    return user_has_role(user, DELIVERY_MANAGEMENT_ROLES)


INVENTORY_MANAGEMENT_ROLES = frozenset({"ADMIN", "SUPERVISOR"})


def can_manage_inventory(user):
    return user_has_role(user, INVENTORY_MANAGEMENT_ROLES)