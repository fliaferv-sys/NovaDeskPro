from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

import json

from django.http import JsonResponse

from .models import Notification, PushSubscription


def _notification_base_queryset(user):
    return Notification.objects.filter(
        Q(recipient=user) | Q(recipient__isnull=True)
    )


@login_required
def notification_list(request):
    search = request.GET.get("q", "").strip()
    level = request.GET.get("level", "").strip()
    notification_type = request.GET.get("type", "").strip()
    status = request.GET.get("status", "active").strip()
    read = request.GET.get("read", "").strip()

    base_queryset = _notification_base_queryset(request.user)

    notifications = base_queryset.order_by(
        "is_read",
        "-created_at",
    )

    if status == "resolved":
        notifications = notifications.filter(is_active=False)
    else:
        notifications = notifications.filter(is_active=True)

    if level:
        notifications = notifications.filter(level=level)

    if notification_type:
        notifications = notifications.filter(
            notification_type=notification_type
        )

    if read == "unread":
        notifications = notifications.filter(is_read=False)
    elif read == "read":
        notifications = notifications.filter(is_read=True)

    if search:
        notifications = notifications.filter(
            Q(title__icontains=search)
            | Q(message__icontains=search)
            | Q(object_type__icontains=search)
            | Q(object_id__icontains=search)
            | Q(unique_key__icontains=search)
        )

    active_notifications = base_queryset.filter(
        is_active=True,
    )

    today = timezone.localdate()

    unread_count = active_notifications.filter(
        is_read=False,
    ).count()

    danger_count = active_notifications.filter(
        level=Notification.LEVEL_DANGER,
    ).count()

    warning_count = active_notifications.filter(
        level=Notification.LEVEL_WARNING,
    ).count()

    info_count = active_notifications.filter(
        level=Notification.LEVEL_INFO,
    ).count()

    resolved_queryset = base_queryset.filter(
        is_active=False,
    )

    resolved_count = resolved_queryset.count()

    resolved_today_count = base_queryset.filter(
        resolved_at__date=today,
    ).count()

    reopened_total_count = base_queryset.filter(
        reopened_at__isnull=False,
    ).count()

    reopened_today_count = base_queryset.filter(
        reopened_at__date=today,
    ).count()

    type_summary = list(
        base_queryset.values(
            "notification_type"
        ).annotate(
            total=Count("id")
        ).order_by("-total")
    )

    type_labels = dict(Notification.TYPE_CHOICES)

    for item in type_summary:
        item["label"] = type_labels.get(
            item["notification_type"],
            item["notification_type"],
        )

    level_summary = list(
        base_queryset.values(
            "level"
        ).annotate(
            total=Count("id")
        ).order_by("-total")
    )

    level_labels = dict(Notification.LEVEL_CHOICES)

    for item in level_summary:
        item["label"] = level_labels.get(
            item["level"],
            item["level"],
        )

    context = {
        "notifications": notifications,
        "unread_count": unread_count,
        "total_count": active_notifications.count(),
        "danger_count": danger_count,
        "warning_count": warning_count,
        "info_count": info_count,
        "resolved_count": resolved_count,
        "resolved_today_count": resolved_today_count,
        "reopened_total_count": reopened_total_count,
        "reopened_today_count": reopened_today_count,
        "type_summary": type_summary,
        "level_summary": level_summary,
        "search": search,
        "selected_level": level,
        "selected_type": notification_type,
        "selected_status": status,
        "selected_read": read,
        "type_choices": Notification.TYPE_CHOICES,
        "level_choices": Notification.LEVEL_CHOICES,
    }

    return render(
        request,
        "notifications/notification_list.html",
        context,
    )


@login_required
@require_POST
def notification_mark_read(request, pk):
    notification = get_object_or_404(
        _notification_base_queryset(request.user),
        pk=pk,
        is_active=True,
    )

    notification.mark_as_read()

    if notification.link:
        return redirect(notification.link)

    return redirect("notifications:notification_list")


@login_required
@require_POST
def notification_mark_all_read(request):
    notifications = _notification_base_queryset(
        request.user
    ).filter(
        is_active=True,
        is_read=False,
    )

    for notification in notifications:
        notification.mark_as_read()

    return redirect("notifications:notification_list")


@login_required
@require_POST
def notification_resolve(request, pk):
    notification = get_object_or_404(
        _notification_base_queryset(request.user),
        pk=pk,
    )

    notification.resolve(user=request.user)

    return redirect("notifications:notification_list")


@login_required
@require_POST
def notification_reopen(request, pk):
    notification = get_object_or_404(
        _notification_base_queryset(request.user),
        pk=pk,
    )

    notification.reopen(user=request.user)

    return redirect("notifications:notification_list")

@login_required
@require_POST
def push_subscribe(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"ok": False, "error": "JSON inválido."},
            status=400,
        )

    endpoint = payload.get("endpoint", "").strip()
    keys = payload.get("keys") or {}
    p256dh = keys.get("p256dh", "").strip()
    auth = keys.get("auth", "").strip()

    if not endpoint or not p256dh or not auth:
        return JsonResponse(
            {
                "ok": False,
                "error": "La suscripción Push está incompleta.",
            },
            status=400,
        )

    subscription, created = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "user": request.user,
            "p256dh": p256dh,
            "auth": auth,
            "user_agent": request.META.get("HTTP_USER_AGENT", ""),
            "is_active": True,
        },
    )

    return JsonResponse(
        {
            "ok": True,
            "created": created,
            "subscription_id": str(subscription.pk),
        }
    )