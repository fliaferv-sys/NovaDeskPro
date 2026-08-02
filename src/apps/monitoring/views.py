import json
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.db import models, transaction
from django.conf import settings

from apps.inventory.models import Asset
from apps.accounts.access import roles_required

from .models import DeviceHeartbeat, DeviceIPHistory


def decimal_or_none(value):
    if value in (None, ""):
        return None

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


@csrf_exempt
@require_POST
@transaction.atomic
def receive_heartbeat(request):
    agent_token = request.headers.get("X-NovaDesk-Agent-Token", "")

    if (
        not settings.NOVADESK_AGENT_TOKEN
        or not secrets.compare_digest(
            agent_token,
            settings.NOVADESK_AGENT_TOKEN,
        )
    ):
        return JsonResponse(
            {
                "success": False,
                "error": "Credencial del agente inválida.",
            },
            status=401,
        )
    if len(request.body) > settings.NOVADESK_HEARTBEAT_MAX_BYTES:
        return JsonResponse(
            {"success": False, "error": "El cuerpo excede el tamaño permitido."},
            status=413,
        )

    try:
        data = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {
                "success": False,
                "error": "El cuerpo de la solicitud no contiene JSON válido.",
            },
            status=400,
        )

    asset_code = str(data.get("asset_code", "")).strip()
    computer_name = str(data.get("computer_name", "")).strip()

  
    if not asset_code:
        return JsonResponse(
            {
                "success": False,
                "error": "El campo asset_code es obligatorio.",
            },
            status=400,
        )

    if not computer_name:
        return JsonResponse(
            {
                "success": False,
                "error": "El campo computer_name es obligatorio.",
            },
            status=400,
        )

    try:
        asset = Asset.objects.select_for_update().get(internal_code=asset_code)
    except Asset.DoesNotExist:
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "No existe un activo con el código "
                    f"{asset_code}."
                ),
            },
            status=404,
        )

    heartbeat, created = DeviceHeartbeat.objects.update_or_create(
        asset=asset,
        defaults={
            "computer_name": computer_name,
            "logged_user": str(data.get("logged_user", "")).strip(),
            "ip_address": data.get("ip_address") or None,
            "mac_address": str(data.get("mac_address", "")).strip(),
            "operating_system": str(
                data.get("operating_system", "")
            ).strip(),
            "processor": str(data.get("processor", "")).strip(),
            "ram_total_gb": decimal_or_none(
                data.get("ram_total_gb")
            ),
            "disk_total_gb": decimal_or_none(
                data.get("disk_total_gb")
            ),
            "disk_free_gb": decimal_or_none(
                data.get("disk_free_gb")
            ),
            "agent_version": str(
                data.get("agent_version", "")
            ).strip(),
            "last_seen": timezone.now(),
        },
    )

    # ==============================================
    # Guardar historial de IPs
    # ==============================================
    current_ip = heartbeat.ip_address

    if current_ip:
        ip_history, history_created = DeviceIPHistory.objects.get_or_create(
            device=heartbeat,
            ip_address=current_ip,
            defaults={
                "computer_name": heartbeat.computer_name,
                "logged_user": heartbeat.logged_user,
                "mac_address": heartbeat.mac_address,
                "first_seen": timezone.now(),
                "last_seen": timezone.now(),
                "detection_count": 1,
            },
        )

        if not history_created:
            ip_history.computer_name = heartbeat.computer_name
            ip_history.logged_user = heartbeat.logged_user
            ip_history.mac_address = heartbeat.mac_address
            ip_history.last_seen = timezone.now()
            DeviceIPHistory.objects.filter(pk=ip_history.pk).update(
                computer_name=heartbeat.computer_name,
                logged_user=heartbeat.logged_user,
                mac_address=heartbeat.mac_address,
                last_seen=timezone.now(),
                detection_count=models.F("detection_count") + 1,
            )

    return JsonResponse(
        {
            "success": True,
            "created": created,
            "heartbeat_id": str(heartbeat.pk),
            "asset_code": asset.internal_code,
            "computer_name": heartbeat.computer_name,
            "ip_address": heartbeat.ip_address,
            "status": heartbeat.status_label,
            "last_seen": heartbeat.last_seen.isoformat(),
        }
    )


@login_required
@roles_required("ADMIN", "SUPERVISOR", "AUDITOR", "TECHNICIAN")
def monitoring_dashboard(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    devices = (
        DeviceHeartbeat.objects
        .select_related("asset")
        .order_by("computer_name")
    )

    if query:
        devices = devices.filter(
            models.Q(ip_address__icontains=query)
            | models.Q(computer_name__icontains=query)
            | models.Q(logged_user__icontains=query)
            | models.Q(mac_address__icontains=query)
            | models.Q(asset__internal_code__icontains=query)
            | models.Q(asset__patrimonial_code__icontains=query)
        )

    online_threshold = timezone.now() - timedelta(minutes=3)
    if status == "online":
        devices = devices.filter(last_seen__gte=online_threshold)
    elif status == "offline":
        devices = devices.filter(
            models.Q(last_seen__lt=online_threshold) | models.Q(last_seen__isnull=True)
        )

    total_count = DeviceHeartbeat.objects.count()
    online_count = DeviceHeartbeat.objects.filter(
        last_seen__gte=online_threshold
    ).count()
    devices_list = list(devices)

    context = {
        "devices": devices_list,
        "online_count": online_count,
        "offline_count": total_count - online_count,
        "total_count": total_count,
        "query": query,
        "selected_status": status,
        "result_count": len(devices_list),
    }

    return render(
        request,
        "monitoring/dashboard.html",
        context,
    )
@login_required
@roles_required("ADMIN", "SUPERVISOR", "AUDITOR", "TECHNICIAN")
def ip_history_list(request):
    query = request.GET.get("q", "").strip()

    history = (
        DeviceIPHistory.objects
        .select_related("device", "device__asset")
        .order_by("-last_seen")
    )

    if query:
        history = history.filter(
            models.Q(ip_address__icontains=query)
            | models.Q(computer_name__icontains=query)
            | models.Q(logged_user__icontains=query)
            | models.Q(mac_address__icontains=query)
            | models.Q(device__asset__internal_code__icontains=query)
            | models.Q(device__asset__patrimonial_code__icontains=query)
        )

    context = {
        "history": history,
        "query": query,
        "result_count": history.count(),
    }

    return render(
        request,
        "monitoring/ip_history.html",
        context,
    )

@login_required
@roles_required("ADMIN", "SUPERVISOR", "AUDITOR", "TECHNICIAN")
def device_detail(request, pk):
    device = get_object_or_404(
    DeviceHeartbeat.objects.select_related(
        "asset",
        "asset__assigned_user",
        "asset__branch",
        "asset__physical_location",
    ),
    pk=pk,
)

    ip_history = (
        device.ip_history
        .all()
        .order_by("-last_seen")
    )

    context = {
        "device": device,
        "ip_history": ip_history,
        "ip_history_count": ip_history.count(),
    }

    return render(
        request,
        "monitoring/device_detail.html",
        context,
    )
