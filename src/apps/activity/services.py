from .models import ActivityLog


def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR")


def register_activity(
    *,
    request=None,
    user=None,
    action=ActivityLog.ACTION_OTHER,
    module="",
    description="",
    object_type="",
    object_id=None,
):
    if request is not None:
        if user is None and request.user.is_authenticated:
            user = request.user

        ip_address = get_client_ip(request)
    else:
        ip_address = None

    return ActivityLog.objects.create(
        user=user,
        action=action,
        module=module,
        description=description,
        object_type=object_type,
        object_id=object_id,
        ip_address=ip_address,
    )