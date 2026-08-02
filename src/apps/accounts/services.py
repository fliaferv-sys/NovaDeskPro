from .models import Department


def get_user_department(user):
    if not hasattr(user, 'role'):
        return None

    role_code = user.role.upper()

    department, created = Department.objects.get_or_create(
        code=role_code,
        defaults={
            "name": role_code.capitalize()
        }
    )

    return department