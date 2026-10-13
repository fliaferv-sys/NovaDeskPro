from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .access import roles_required
from .models import User
from .institutional_sync import apply_user_institutional_sync


@login_required
@roles_required("ADMIN", "SUPERVISOR")
@require_POST
def sync_user_institutional_data(request, pk):
    target = get_object_or_404(User, pk=pk)
    try:
        plan = apply_user_institutional_sync(target, actor=request.user)
        if not plan["can_apply"]:
            messages.warning(request, "No se sincronizó automáticamente. Requiere revisión.")
        elif plan["proposed_changes"]:
            labels = {"id_personal": "IdPersonal", "employee_number": "legajo", "phone": "teléfono", "position": "cargo"}
            messages.success(request, "Se actualizaron: " + ", ".join(labels[field] for field in plan["proposed_changes"]) + ".")
            if plan["conflicts"]:
                messages.warning(request, "Se conservaron datos locales distintos. Requieren revisión.")
        elif plan["conflicts"]:
            messages.warning(request, "No se sincronizó automáticamente. Requiere revisión.")
        else:
            messages.info(request, "Los datos ya están sincronizados.")
    except Exception:
        messages.error(request, "No se sincronizó automáticamente. Requiere revisión.")
    return redirect("user_list")
