from django.contrib.auth.decorators import (
    login_required,
    permission_required,
)
from django.contrib import messages
from django.core.exceptions import PermissionDenied

from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)

from django.http import FileResponse, JsonResponse
from django.views.decorators.http import require_POST

from django.utils import timezone
from django.db import transaction
from django.db.models import Q

from apps.activity.models import ActivityLog
from apps.activity.services import register_activity

from apps.core.models import Department, TicketCategory
from apps.tickets.services import auto_assign_ticket

from apps.accounts.services import get_user_department
from .authorization_pdf import generate_authorization_pdf

from .forms import (
    AuthorizationDocumentForm,
    SystemAccessRequestForm,
    TicketAssignForm,
    TicketAttachmentForm,
    TicketCommentForm,
    TicketForm,
    TicketTransferForm,
)
from .models import (
    Ticket,
    TicketComment,
    QuickAction,
    SystemAccessRequest,
    AuthorizationDocument,
    AccessIdentityDocument,
    TicketAttachment,
)
from .selectors import (
    get_user_position_in_queue,
    get_user_dashboard_stats,
    get_user_active_ticket,
    get_user_recent_tickets,
    get_queue_stats,
)
from django.urls import reverse
from django.views.decorators.cache import never_cache


TICKET_GLOBAL_ROLES = {"AUDITOR"}
TICKET_DEPARTMENT_ROLES = {"ADMIN", "SUPERVISOR", "TECHNICIAN"}


def can_view_ticket(user, ticket):
    if user.is_superuser or user.role in TICKET_GLOBAL_ROLES:
        return True
    if ticket.requester_id == user.pk or ticket.assigned_to_id == user.pk:
        return True
    return (
        user.role in TICKET_DEPARTMENT_ROLES
        and user.department_id is not None
        and ticket.department_id == user.department_id
    )


def can_manage_ticket(user, ticket):
    if user.is_superuser:
        return True
    return (
        user.role in TICKET_DEPARTMENT_ROLES
        and user.department_id is not None
        and ticket.department_id == user.department_id
    )


def can_edit_own_ticket(user, ticket):
    return ticket.requester_id == user.pk and ticket.status == "OPEN"


def require_ticket_view_access(user, ticket):
    if not can_view_ticket(user, ticket):
        raise PermissionDenied("No tiene acceso a este ticket.")


def require_ticket_management_access(user, ticket):
    if not can_manage_ticket(user, ticket):
        raise PermissionDenied("No tiene permisos para gestionar este ticket.")


@login_required
@never_cache
def ticket_attachment_download_view(request, pk, attachment_id):
    ticket = get_object_or_404(Ticket, pk=pk)
    require_ticket_view_access(request.user, ticket)
    attachment = get_object_or_404(
        TicketAttachment, pk=attachment_id, ticket=ticket
    )
    return FileResponse(
        attachment.file.open("rb"),
        as_attachment=request.GET.get("download") == "1",
        filename=attachment.original_name,
        content_type=attachment.content_type or "application/octet-stream",
    )


@login_required
@never_cache
def authorization_document_download_view(request, pk, document_id):
    ticket = get_object_or_404(Ticket, pk=pk)
    require_ticket_view_access(request.user, ticket)
    document = get_object_or_404(
        AuthorizationDocument,
        pk=document_id,
        access_request__ticket=ticket,
    )
    return FileResponse(
        document.file.open("rb"),
        filename=document.original_name,
        content_type=document.content_type or "application/octet-stream",
    )


@login_required
@never_cache
def identity_document_download_view(request, pk, document_id):
    ticket = get_object_or_404(Ticket, pk=pk)
    require_ticket_view_access(request.user, ticket)
    document = get_object_or_404(
        AccessIdentityDocument,
        pk=document_id,
        access_request__ticket=ticket,
    )
    return FileResponse(
        document.file.open("rb"),
        filename=document.original_name,
        content_type=document.content_type or "application/octet-stream",
    )


# ==========================================================
# FUNCIÓN AUXILIAR PARA OBTENER DEPARTMENT
# ==========================================================

def get_user_department(user):
    """Obtiene el departamento del usuario si no es CLIENT."""
    if user.role == "CLIENT":
        return None
    
    if user.department_id:
        return user.department
    return Department.objects.filter(code=user.role).first()


# ==========================================================
# VISTAS DE TICKETS
# ==========================================================

@login_required
def ticket_list_view(request):
    user = request.user

    # 1. Solo superusuarios y auditores tienen visibilidad global.
    if user.is_superuser or user.role in TICKET_GLOBAL_ROLES:
        tickets = Ticket.objects.all()

    # 2. Clientes ven SOLO sus tickets
    elif user.role == "CLIENT":
        tickets = Ticket.objects.filter(requester=user)

    # 3. Administradores, supervisores y técnicos trabajan por departamento.
    elif user.role in TICKET_DEPARTMENT_ROLES:
        user_dept = None
        
        if hasattr(user, 'department') and user.department:
            user_dept = user.department
        if user_dept:
            tickets = Ticket.objects.filter(department=user_dept)
        else:
            tickets = Ticket.objects.none()

    # 4. Cualquier otro rol queda sin bandeja operativa.
    else:
        tickets = Ticket.objects.none()

    total_tickets = tickets.count()
    resolved_tickets = tickets.filter(status__in=["RESOLVED", "CLOSED"]).count()
    pending_tickets = tickets.filter(status__in=["OPEN", "IN_PROGRESS", "WAITING"]).count()

    department = get_user_department(request.user)
    

    return render(
        request,
        "tickets/ticket_list.html",
        {
            "tickets": tickets,
            "total_tickets": total_tickets,
            "resolved_tickets": resolved_tickets,
            "pending_tickets": pending_tickets,
            "department": department,
        },
    )


@login_required
@transaction.atomic
def ticket_create_view(request):
    # ==========================================================
    # DEPURACIÓN - ENTRADA A LA VISTA
    # ==========================================================
    department = get_user_department(request.user)
    
    departments = Department.objects.filter(
        is_active=True
    ).prefetch_related('ticket_categories')
    
    # ==========================================================
    # OBTENER ACCESOS RÁPIDOS
    # ==========================================================
    quick_actions = list(QuickAction.objects.filter(
        is_active=True
    ).select_related('department').order_by('department', 'order'))

    support_department = departments.filter(code="SUPPORT").first()
    if support_department and not any(
        action.department_id == support_department.pk
        for action in quick_actions
    ):
        quick_actions.append(
            QuickAction(
                title="Alta o baja de usuario",
                description="Solicitud formal de usuario",
                department=support_department,
                label="Soporte DTI",
                icon="bi-person-plus",
                order=0,
            )
        )

    quick_actions.sort(
        key=lambda action: (action.department.name, action.order, action.title)
    )
    request_flow = "OPERATIONAL"
    request_kind = ""
    
    # ==========================================================
    # DEPURACIÓN - ACCESOS RÁPIDOS ENCONTRADOS
    # ==========================================================

    if request.method == "POST":
        form = TicketForm(
            request.POST,
            user=request.user,
        )

        access_request_form = SystemAccessRequestForm(
            request.POST,
            prefix="access",
        )

        authorization_document_form = AuthorizationDocumentForm(
            request.POST,
            request.FILES,
            prefix="authorization",
        )

        request_flow = request.POST.get("request_flow")
        request_kind = request.POST.get("request_kind", "")
        access_form_is_valid = (
            request_flow != "AUTHORIZATION"
            or request_kind == "USER_CREATION_DOCUMENTS"
            or access_request_form.is_valid()
        )
        document_form_is_valid = (
            request_kind != "USER_CREATION_DOCUMENTS"
            or authorization_document_form.is_valid()
        )

        if (
            form.is_valid()
            and access_form_is_valid
            and document_form_is_valid
        ):
            ticket = form.save(commit=False)
            ticket.requester = request.user

            # ===============================
            # MAPEO DE CATEGORÍA → DEPARTAMENTO
            # ===============================
            
            category_name = ticket.category
            try:
                category_obj = TicketCategory.objects.get(
                    name=category_name,
                    is_active=True
                )
                ticket.department = category_obj.department
            except TicketCategory.DoesNotExist:
                CATEGORY_DEPARTMENT_MAP = {
                    "SOFTWARE": "SYSTEMS",
                    "HARDWARE": "SUPPORT",
                    "NETWORK": "SUPPORT",
                    "PRINTER": "SUPPORT",
                    "SAP": "SAP",
                    "SAP_ERROR": "SAP",
                    "SAP_SLOW": "SAP",
                    "SAP_PRINT": "SAP",
                    "SAP_USER": "SAP",
                    "SYSTEM_ERROR": "SYSTEMS",
                    "DATABASE": "SYSTEMS",
                    "EMAIL": "SYSTEMS",
                    "PASSWORD_RESET": "SYSTEMS",
                    "USER_BLOCKED": "SYSTEMS",
                    "INTEGRATION": "SYSTEMS",
                    "POWER_OUTAGE": "ELECTRICITY",
                    "GENERATOR": "ELECTRICITY",
                    "ELECTRICAL_PANEL": "ELECTRICITY",
                    "LIGHTING": "ELECTRICITY",
                    "OVERLOAD": "ELECTRICITY",
                    "FUEL_SUPPLY": "FUELFACS",
                    "FUEL_PUMP": "FUELFACS",
                    "FUEL_INVENTORY": "FUELFACS",
                    "FUEL_METER": "FUELFACS",
                }
                dept_code = CATEGORY_DEPARTMENT_MAP.get(ticket.category, "SUPPORT")
                ticket.department = Department.objects.get(code=dept_code)

            ticket.save()

            assigned_technician = auto_assign_ticket(ticket)

            if assigned_technician:
                TicketComment.objects.create(
                    ticket=ticket,
                    author=request.user,
                    message=(
                        "🤖 Ticket asignado automáticamente a "
                        f"{assigned_technician.get_full_name() or assigned_technician.email} "
                        "por menor carga de trabajo."
                    ),
                    is_system=True,
                    comment_type="ASSIGN",
                )

                register_activity(
                    request=request,
                    action=ActivityLog.ACTION_ASSIGN,
                    module="Tickets",
                    description=(
                        f"El ticket {ticket.ticket_number} fue asignado "
                        "automáticamente a "
                        f"{assigned_technician.get_full_name() or assigned_technician.email} "
                        f"por menor carga del departamento "
                        f"{ticket.department}."
                    ),
                    object_type="Ticket",
                    object_id=str(ticket.pk),
                )

            # ==========================================================
            # CREAR SOLICITUD FORMAL DE ACCESO
            # ==========================================================

            if request_flow == "AUTHORIZATION":

                is_document_based_user_creation = (
                    request_kind == "USER_CREATION_DOCUMENTS"
                )

                access_request = SystemAccessRequest.objects.create(

                    ticket=ticket,

                    requested_system=(
                        "CORREO_WINDOWS"
                        if is_document_based_user_creation
                        else request.POST.get("access-requested_system", "")
                    ),

                    operation=(
                        SystemAccessRequest.RequestOperation.USER_CREATION
                        if is_document_based_user_creation
                        else request.POST.get("access-operation", "")
                    ),

                    affected_employee=(
                        request.user.get_full_name() or request.user.email
                        if is_document_based_user_creation
                        else request.POST.get("access-affected_employee", "")
                    ),

                    employee_number=(
                        request.user.employee_number or ""
                        if is_document_based_user_creation
                        else request.POST.get("access-employee_number", "")
                    ),

                    affected_document_number=(
                        request.user.document_number or ""
                        if is_document_based_user_creation
                        else request.POST.get(
                            "access-affected_document_number", ""
                        )
                    ),

                    requested_email=(
                        request.user.email
                        if is_document_based_user_creation
                        else request.POST.get("access-requested_email", "")
                    ),

                    employee_department=(
                        str(request.user.department or "")
                        if is_document_based_user_creation
                        else request.POST.get("access-employee_department", "")
                    ),

                    employee_position=(
                        request.user.position or ""
                        if is_document_based_user_creation
                        else request.POST.get("access-employee_position", "")
                    ),

                    requested_permissions=(
                        "Creacion de usuario para Correo y Windows"
                        if is_document_based_user_creation
                        else request.POST.get("access-requested_permissions", "")
                    ),

                    justification=(
                        ticket.description
                        if is_document_based_user_creation
                        else request.POST.get("access-justification", "")
                    ),

                    authorizing_director=(
                        "Indicado en los formularios firmados"
                        if is_document_based_user_creation
                        else request.POST.get("access-authorizing_director", "")
                    ),

                    observations=request.POST.get(
                        "access-observations",
                        ""
                    ),

                    authorization_status=(
                        SystemAccessRequest.AuthorizationStatus.FORM_ATTACHED
                        if is_document_based_user_creation
                        else SystemAccessRequest.AuthorizationStatus.PENDING_FORM
                    )
                )

                if is_document_based_user_creation:
                    signed_file = request.FILES["authorization-file"]
                    identity_file = request.FILES[
                        "authorization-identity_file"
                    ]

                    AuthorizationDocument.objects.create(
                        access_request=access_request,
                        file=signed_file,
                        original_name=signed_file.name,
                        content_type=signed_file.content_type or "",
                        size=signed_file.size,
                        version=1,
                        validation_status=(
                            AuthorizationDocument.ValidationStatus.PENDING
                        ),
                        uploaded_by=request.user,
                    )

                    AccessIdentityDocument.objects.create(
                        access_request=access_request,
                        file=identity_file,
                        original_name=identity_file.name,
                        content_type=identity_file.content_type or "",
                        size=identity_file.size,
                        version=1,
                        uploaded_by=request.user,
                    )

                                # ==========================================================
                # GUARDAR DOCUMENTO FIRMADO DE AUTORIZACIÓN
                # ==========================================================

                register_activity(
                    request=request,
                    action=ActivityLog.ACTION_CREATE,
                    module="Tickets",
                    description=(
                        "Se registro la solicitud de acceso para "
                        f"{access_request.affected_employee} con los tres "
                        "formularios firmados y la fotocopia de cedula."
                    ),
                    object_type="SystemAccessRequest",
                    object_id=str(access_request.pk),
                )


            register_activity(
                request=request,
                action=ActivityLog.ACTION_CREATE,
                module="Tickets",
                description=(
                    f"Se creó el ticket "
                    f"{ticket.ticket_number}: {ticket.title}."
                ),
                object_type="Ticket",
                object_id=str(ticket.pk),
            )

            return redirect("tickets:ticket_list")

    else:
        form = TicketForm(
            user=request.user,
        )

        access_request_form = SystemAccessRequestForm(
            prefix="access",
        )

        authorization_document_form = AuthorizationDocumentForm(
            prefix="authorization",
        )

    # ==========================================================
    # DEPURACIÓN - ENVIANDO AL TEMPLATE
    # ==========================================================

    return render(
        request,
        "tickets/ticket_form.html",
        {
            "form": form,
            "access_request_form": access_request_form,
            "authorization_document_form": authorization_document_form,
            "department": department,
            "departments": departments,
            "quick_actions": quick_actions,
            "editing": False,
            "request_flow": request_flow,
            "request_kind": request_kind,
        },
    )


@login_required
@never_cache
@transaction.atomic
def ticket_detail_view(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    require_ticket_view_access(request.user, ticket)

    # ============================================================
    # 🚀 CALCULAR POSICIÓN EN COLA
    # ============================================================
    queue_position = None
    tickets_before = 0
    estimated_time = 0
    
    # Solo calcular si el ticket está en estado activo
    if ticket.status in ['OPEN', 'IN_PROGRESS', 'PENDING']:
        tickets_before = Ticket.objects.filter(
            status__in=['OPEN', 'IN_PROGRESS', 'PENDING'],
            created_at__lt=ticket.created_at
        ).count()
        queue_position = tickets_before + 1
        estimated_time = tickets_before * 15
        if estimated_time == 0:
            estimated_time = 5

        comments = ticket.comments.all()
        latest_comment = comments.order_by("-created_at").first()
        conversation_revision = (
            f"{comments.count()}:{latest_comment.pk if latest_comment else 'empty'}"
        )
        attachments = ticket.attachments.all()

        conversation_items = [
        {
            "type": "comment",
            "date": comment.created_at,
            "object": comment,
        }
        for comment in comments
        
    ]

    conversation_items.extend(
        [
            {
                "type": "attachment",
                "date": attachment.created_at,
                "object": attachment,
            }
            for attachment in attachments
        ]
    )

    conversation_items.sort(key=lambda item: item["date"])
    

    comment_form = TicketCommentForm()
    assign_form = TicketAssignForm(instance=ticket, department=ticket.department)
    transfer_form = TicketTransferForm(current_department=ticket.department)
    attachment_form = TicketAttachmentForm()
    authorization_document_form = AuthorizationDocumentForm()

    department = get_user_department(request.user)

    if request.method == "POST":
        form_type = request.POST.get("form_type")

        # ==================================================
        # GUARDAR COMENTARIO
        # ==================================================

        if form_type == "comment":
            inline_file = request.FILES.get("attachment")
            comment_data = request.POST.copy()
            if inline_file and not comment_data.get("message", "").strip():
                comment_data["message"] = "Archivo adjunto."
            comment_form = TicketCommentForm(comment_data)
            inline_attachment_form = None
            if inline_file:
                inline_attachment_form = TicketAttachmentForm(
                    {},
                    {"file": inline_file},
                )

            forms_are_valid = comment_form.is_valid() and (
                inline_attachment_form is None
                or inline_attachment_form.is_valid()
            )

            if forms_are_valid:
                if ticket.assigned_to_id is None:
                    if request.user.role != "TECHNICIAN":
                        messages.error(
                            request,
                            "Debe asignar un tecnico responsable antes de responder.",
                        )
                        return redirect(
                            "tickets:ticket_detail",
                            pk=ticket.pk,
                        )

                    ticket.assigned_to = request.user
                    status_changed = ticket.status == Ticket.Status.OPEN
                    if status_changed:
                        ticket.status = Ticket.Status.IN_PROGRESS
                    ticket.save(
                        update_fields=["assigned_to", "status", "updated_at"]
                    )

                    ticket.comments.create(
                        author=request.user,
                        message=(
                            f"Ticket autoasignado a "
                            f"{request.user.get_full_name() or request.user.email} "
                            "al responder por primera vez."
                        ),
                        is_system=True,
                        comment_type="ASSIGN",
                    )

                    register_activity(
                        request=request,
                        action=ActivityLog.ACTION_ASSIGN,
                        module="Tickets",
                        description=(
                            f"El ticket {ticket.ticket_number} se autoasigno "
                            f"a {request.user.get_full_name() or request.user.email} "
                            "al responder."
                        ),
                        object_type="Ticket",
                        object_id=str(ticket.pk),
                    )

                    if status_changed:
                        ticket.comments.create(
                            author=request.user,
                            message="Estado cambiado automaticamente a 'En proceso'.",
                            is_system=True,
                            comment_type="STATUS",
                        )
                        register_activity(
                            request=request,
                            action=ActivityLog.ACTION_STATUS,
                            module="Tickets",
                            description=(
                                f"El ticket {ticket.ticket_number} cambio "
                                "automaticamente de 'Abierto' a 'En proceso' "
                                "al asignarse un tecnico."
                            ),
                            object_type="Ticket",
                            object_id=str(ticket.pk),
                        )

                comment = comment_form.save(commit=False)
                comment.ticket = ticket
                comment.author = request.user
                comment.save()

                if inline_attachment_form is not None:
                    attachment = inline_attachment_form.save(commit=False)
                    attachment.ticket = ticket
                    attachment.uploaded_by = request.user
                    attachment.original_name = inline_file.name
                    attachment.content_type = inline_file.content_type or ""
                    attachment.size = inline_file.size
                    attachment.save()

                    ticket.comments.create(
                        author=request.user,
                        message=(
                            f"Se adjuntó el archivo "
                            f"'{attachment.original_name}' al mensaje."
                        ),
                        is_system=True,
                        comment_type="ATTACHMENT",
                    )
                    register_activity(
                        request=request,
                        action=ActivityLog.ACTION_CREATE,
                        module="Tickets",
                        description=(
                            f"Se adjuntó '{attachment.original_name}' al "
                            f"ticket {ticket.ticket_number}."
                        ),
                        object_type="Ticket",
                        object_id=str(ticket.pk),
                    )

                register_activity(
                    request=request,
                    action=ActivityLog.ACTION_COMMENT,
                    module="Tickets",
                    description=(
                        f"Se agregó un comentario al ticket "
                        f"{ticket.ticket_number}."
                    ),
                    object_type="Ticket",
                    object_id=str(ticket.pk),
                )

                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    latest_comment = ticket.comments.order_by(
                        "-created_at"
                    ).first()
                    return JsonResponse(
                        {
                            "success": True,
                            "revision": (
                                f"{ticket.comments.count()}:"
                                f"{latest_comment.pk}"
                            ),
                        }
                    )

                ticket_url = reverse(
                    "tickets:ticket_detail",
                    kwargs={"pk": ticket.pk},
                )
                return redirect(f"{ticket_url}?sent={comment.pk}")

            if inline_attachment_form is not None:
                for errors in inline_attachment_form.errors.values():
                    for error in errors:
                        messages.error(request, error)

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                errors = []
                for form_errors in comment_form.errors.values():
                    errors.extend(str(error) for error in form_errors)
                if inline_attachment_form is not None:
                    for form_errors in inline_attachment_form.errors.values():
                        errors.extend(str(error) for error in form_errors)
                return JsonResponse(
                    {
                        "success": False,
                        "errors": errors or ["No fue posible enviar el mensaje."],
                    },
                    status=400,
                )

        # ==================================================
        # ASIGNAR TÉCNICO Y CAMBIAR ESTADO
        # ==================================================

        elif form_type == "assign":
            require_ticket_management_access(request.user, ticket)
            old_status = ticket.get_status_display()
            old_technician = ticket.assigned_to

            assign_form = TicketAssignForm(
                request.POST,
                instance=ticket,
                department=ticket.department,
            )

            if assign_form.is_valid():
                ticket = assign_form.save()

                if (
                    ticket.assigned_to_id is not None
                    and ticket.status == Ticket.Status.OPEN
                ):
                    ticket.status = Ticket.Status.IN_PROGRESS
                    ticket.save(update_fields=["status", "updated_at"])

                if old_technician != ticket.assigned_to:
                    technician_name = (
                        f"{ticket.assigned_to.first_name} "
                        f"{ticket.assigned_to.last_name}"
                        if ticket.assigned_to
                        else "Sin asignar"
                    )

                    ticket.comments.create(
                        author=request.user,
                        message=(
                            f"📌 Ticket asignado a "
                            f"{technician_name}."
                        ),
                        is_system=True,
                        comment_type="ASSIGN",
                    )

                    register_activity(
                        request=request,
                        action=ActivityLog.ACTION_ASSIGN,
                        module="Tickets",
                        description=(
                            f"El ticket {ticket.ticket_number} "
                            f"fue asignado a {technician_name}."
                        ),
                        object_type="Ticket",
                        object_id=str(ticket.pk),
                    )

                if old_status != ticket.get_status_display():
                    new_status = ticket.get_status_display()

                    ticket.comments.create(
                        author=request.user,
                        message=(
                            "🔄 Estado cambiado a "
                            f"'{new_status}'."
                        ),
                        is_system=True,
                        comment_type="STATUS",
                    )

                    register_activity(
                        request=request,
                        action=ActivityLog.ACTION_STATUS,
                        module="Tickets",
                        description=(
                            f"El estado del ticket "
                            f"{ticket.ticket_number} cambió de "
                            f"'{old_status}' a '{new_status}'."
                        ),
                        object_type="Ticket",
                        object_id=str(ticket.pk),
                    )

                return redirect("tickets:ticket_detail", pk=ticket.pk)

        # ==================================================
        # DERIVAR A OTRA ÁREA O DEPARTAMENTO
        # ==================================================

        elif form_type == "transfer":
            require_ticket_management_access(request.user, ticket)
            transfer_form = TicketTransferForm(
                request.POST,
                current_department=ticket.department,
            )

            if transfer_form.is_valid():
                origin_department = ticket.department
                destination = transfer_form.cleaned_data[
                    "destination_department"
                ]
                reason = transfer_form.cleaned_data["reason"].strip()
                origin_name = (
                    origin_department.name
                    if origin_department
                    else "Sin departamento"
                )

                ticket.department = destination
                ticket.assigned_to = None
                ticket.status = Ticket.Status.OPEN
                ticket.due_date = None
                ticket.sla_status = None
                if destination.code in dict(Ticket.Group.choices):
                    ticket.assigned_group = destination.code
                ticket.save()

                transfer_message = (
                    f"Ticket derivado de {origin_name} a {destination.name}. "
                    f"Motivo: {reason}"
                )
                ticket.comments.create(
                    author=request.user,
                    message=transfer_message,
                    is_system=True,
                    comment_type="STATUS",
                )
                register_activity(
                    request=request,
                    action=ActivityLog.ACTION_OTHER,
                    module="Tickets",
                    description=(
                        f"El ticket {ticket.ticket_number} fue derivado "
                        f"de {origin_name} a {destination.name} por "
                        f"{request.user.get_full_name() or request.user.email}. "
                        f"Motivo: {reason}"
                    ),
                    object_type="Ticket",
                    object_id=str(ticket.pk),
                )
                messages.success(
                    request,
                    f"Ticket derivado correctamente a {destination.name}.",
                )
                return redirect("tickets:ticket_list")

        # ==================================================
        # GUARDAR ARCHIVO ADJUNTO
        # ==================================================

        elif form_type == "attachment":
            attachment_form = TicketAttachmentForm(
                request.POST,
                request.FILES,
            )

            if attachment_form.is_valid():
                uploaded_file = request.FILES["file"]

                attachment = attachment_form.save(commit=False)
                attachment.ticket = ticket
                attachment.uploaded_by = request.user
                attachment.original_name = uploaded_file.name
                attachment.content_type = (
                    uploaded_file.content_type or ""
                )
                attachment.size = uploaded_file.size
                attachment.save()

                uploader_name = (
                    f"{request.user.first_name} "
                    f"{request.user.last_name}"
                ).strip() or request.user.email

                ticket.comments.create(
                    author=request.user,
                    message=(
                        f"{uploader_name} adjuntó el archivo "
                        f"'{attachment.original_name}' "
                        f"({attachment.size / 1024:.1f} KB)."
                    ),
                    is_system=True,
                    comment_type="ATTACHMENT",
                )
                register_activity(
                    request=request,
                    action=ActivityLog.ACTION_CREATE,
                    module="Tickets",
                    description=(
                        f"Se creó el ticket "
                        f"{ticket.ticket_number}: {ticket.title}."
                    ),
                    object_type="Ticket",
                    object_id=str(ticket.pk),
                )

                return redirect(
                    "tickets:ticket_detail",
                    pk=ticket.pk,
                )
                # ==================================================
        # GUARDAR FORMULARIO DE AUTORIZACIÓN FIRMADO
        # ==================================================

        elif form_type == "authorization_document":

            access_request = getattr(
                ticket,
                "system_access_request",
                None,
            )

            if access_request is None:
                return redirect(
                    "tickets:ticket_detail",
                    pk=ticket.pk,
                )

            authorization_document_form = AuthorizationDocumentForm(
                request.POST,
                request.FILES,
            )

            if authorization_document_form.is_valid():
                uploaded_file = request.FILES["file"]

                previous_documents = (
                    access_request.authorization_documents.exclude(
                        validation_status=(
                            AuthorizationDocument
                            .ValidationStatus
                            .REPLACED
                        )
                    )
                )

                previous_documents.update(
                    validation_status=(
                        AuthorizationDocument
                        .ValidationStatus
                        .REPLACED
                    )
                )

                next_version = (
                    access_request.authorization_documents.count()
                    + 1
                )

                identity_file = (
                    authorization_document_form.cleaned_data["identity_file"]
                )

                document = authorization_document_form.save(
                    commit=False
                )

                document.access_request = access_request
                document.original_name = uploaded_file.name
                document.content_type = (
                    uploaded_file.content_type or ""
                )
                document.size = uploaded_file.size
                document.version = next_version
                document.uploaded_by = request.user
                document.validation_status = (
                    AuthorizationDocument
                    .ValidationStatus
                    .PENDING
                )

                document.save()

                AccessIdentityDocument.objects.create(
                    access_request=access_request,
                    file=identity_file,
                    original_name=identity_file.name,
                    content_type=identity_file.content_type or "",
                    size=identity_file.size,
                    version=next_version,
                    uploaded_by=request.user,
                )

                access_request.authorization_status = (
                    SystemAccessRequest
                    .AuthorizationStatus
                    .FORM_ATTACHED
                )

                access_request.save(
                    update_fields=[
                        "authorization_status",
                        "updated_at",
                    ]
                )

                uploader_name = (
                    request.user.get_full_name()
                    or request.user.username
                )

                ticket.comments.create(
                    author=request.user,
                    message=(
                        f"📄 {uploader_name} adjuntó el "
                        f"formulario firmado "
                        f"'{document.original_name}' y la fotocopia de cedula."
                    ),
                    is_system=True,
                    comment_type="ATTACHMENT",
                )

                register_activity(
                    request=request,
                    action=ActivityLog.ACTION_CREATE,
                    module="Tickets",
                    description=(
                        f"Se adjuntó el formulario firmado "
                        f"'{document.original_name}' con fotocopia de cedula en el "
                        f"ticket {ticket.ticket_number}. "
                        f"Versión {document.version}."
                    ),
                    object_type="Ticket",
                    object_id=str(ticket.pk),
                )

                return redirect(
                    "tickets:ticket_detail",
                    pk=ticket.pk,
                )
            
    activity_logs = ActivityLog.objects.filter(
        object_type="Ticket",
        object_id=str(ticket.pk)
    ).exclude(
        action=ActivityLog.ACTION_COMMENT,
    )

    activity_timeline = [
        {
            "user": log.user,
            "description": log.description,
            "created_at": log.created_at,
            "event_type": "activity",
        }
        for log in activity_logs
    ]
    activity_timeline.extend(
        {
            "user": comment.author,
            "description": comment.message,
            "created_at": comment.created_at,
            "event_type": "message",
        }
        for comment in comments
        if not comment.is_system
    )
    activity_timeline.sort(
        key=lambda event: event["created_at"],
        reverse=True,
    )

    return render(
        request,
        "tickets/ticket_detail.html",
        {
            "ticket": ticket,
            "asset": ticket.asset,
            "comments": comments,
            "conversation_revision": conversation_revision,
            "attachments": attachments,
            "conversation_items": conversation_items,
            "comment_form": comment_form,
            "assign_form": assign_form,
            "transfer_form": transfer_form,
            "can_manage_ticket": can_manage_ticket(request.user, ticket),
            "attachment_form": attachment_form,
            "authorization_document_form": authorization_document_form,
            "department": department,
            "activity_logs": activity_timeline,
            "queue_position": queue_position,        # 👈 NUEVO
            "tickets_before": tickets_before,        # 👈 NUEVO
            "estimated_time": estimated_time,        # 👈 NUEVO

            # ==================================================
            # SOLICITUD FORMAL DE ACCESO
            # ==================================================
            "system_access_request": getattr(
                ticket,
                "system_access_request",
                None
            ),
        },
    )


@login_required
def ticket_update_view(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    if not (
        can_manage_ticket(request.user, ticket)
        or can_edit_own_ticket(request.user, ticket)
    ):
        raise PermissionDenied("No tiene permisos para editar este ticket.")
    department = get_user_department(request.user)

    departments = Department.objects.filter(
        is_active=True
    ).prefetch_related('ticket_categories')

    if request.method == "POST":
        form = TicketForm(
            request.POST,
            instance=ticket,
            user=ticket.requester,
        )

        if form.is_valid():
            ticket = form.save()

            register_activity(
                request=request,
                action=ActivityLog.ACTION_UPDATE,
                module="Tickets",
                description=(
                    f"Se actualizó el ticket "
                    f"{ticket.ticket_number}: {ticket.title}."
                ),
                object_type="Ticket",
                object_id=str(ticket.pk),
            )

            return redirect(
                "tickets:ticket_detail",
                pk=ticket.pk,
            )
    else:
        form = TicketForm(
            instance=ticket,
            user=ticket.requester,
        )

    return render(
        request,
        "tickets/ticket_form.html",
        {
            "form": form,
            "editing": True,
            "ticket": ticket,
            "department": department,
            "departments": departments,
        },
    )


@login_required
def ticket_delete_view(request, pk):
    ticket = get_object_or_404(
        Ticket,
        pk=pk,
    )

    require_ticket_management_access(request.user, ticket)
    department = get_user_department(request.user)

    if request.method == "POST":
        ticket_number = ticket.ticket_number
        ticket_title = ticket.title
        ticket_id = str(ticket.pk)

        ticket.delete()

        register_activity(
            request=request,
            action=ActivityLog.ACTION_DELETE,
            module="Tickets",
            description=(
                f"Se eliminó el ticket "
                f"{ticket_number}: {ticket_title}."
            ),
                object_type="Ticket",
                object_id=ticket_id,
        )

        return redirect("tickets:ticket_list")

    return render(
        request,
        "tickets/ticket_confirm_delete.html",
        {
            "ticket": ticket,
            "department": department,
        },
    )


@login_required
def ticket_conversation_status_view(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    require_ticket_view_access(request.user, ticket)
    comments = ticket.comments.all()
    latest_comment = comments.order_by("-created_at").first()
    revision = (
        f"{comments.count()}:{latest_comment.pk if latest_comment else 'empty'}"
    )
    response = JsonResponse({"revision": revision})
    response["Cache-Control"] = "no-store"
    return response


# ==========================================================
# VISTA DEL DASHBOARD
# ==========================================================

@login_required
def dashboard_view(request):
    """
    Dashboard del usuario con:
    - Posición en cola
    - Ticket activo
    - Estadísticas
    - Historial reciente
    """
    user = request.user

    queue_data = get_user_position_in_queue(user)
    stats = get_user_dashboard_stats(user)
    active_ticket = get_user_active_ticket(user)
    recent_tickets = get_user_recent_tickets(user)
    queue_stats = get_queue_stats()

    is_technician = False
    is_admin = False

    if hasattr(user, 'role'):
        is_technician = user.role in TICKET_DEPARTMENT_ROLES
        is_admin = user.role == 'ADMIN'

    department = get_user_department(request.user)

    

    context = {
        'queue_data': queue_data,
        'stats': stats,
        'active_ticket': active_ticket,
        'recent_tickets': recent_tickets,
        'queue_stats': queue_stats,
        'is_technician': is_technician,
        'is_admin': is_admin,
        'department': department,
    }

    return render(
        request,
        'tickets/dashboard.html',
        context
    )

# ==========================================================
# VALIDAR SOLICITUD DE ACCESO
# ==========================================================

@login_required
@permission_required(
    "tickets.validate_access_request",
    raise_exception=True,
)
@require_POST
def validate_access_request_view(request, pk):

    ticket = get_object_or_404(
        Ticket,
        pk=pk
    )

    access_request = get_object_or_404(
        SystemAccessRequest,
        ticket=ticket
    )

    document = (
        access_request.authorization_documents
        .filter(
            validation_status=(
                AuthorizationDocument
                .ValidationStatus
                .PENDING
            )
        )
        .first()
    )
    identity_document = (
        access_request.identity_documents
        .filter(version=document.version)
        .first()
        if document
        else None
    )

    if (
        access_request.authorization_status
        != SystemAccessRequest.AuthorizationStatus.FORM_ATTACHED
        or document is None
        or identity_document is None
    ):
        return redirect(
            "tickets:ticket_detail",
            pk=ticket.pk,
        )

    if request.method == "POST":

        action = request.POST.get("action")

        old_status = (
            access_request.get_authorization_status_display()
        )

        if action == "approve":

            access_request.authorization_status = (
                SystemAccessRequest.AuthorizationStatus.AUTHORIZED
            )

            access_request.save()


            if document:

                document.validation_status = (
                    AuthorizationDocument.ValidationStatus.APPROVED
                )

                document.validated_by = request.user
                document.validated_at = timezone.now()
                document.save()


            register_activity(
                request=request,
                action=ActivityLog.ACTION_STATUS,
                module="Tickets",
                description=(
                    f"Se aprobó solicitud de acceso "
                    f"{access_request.requested_system}. "
                    f"Estado cambiado de {old_status} "
                    f"a Autorizado para procesar."
                ),
                object_type="Ticket",
                object_id=str(ticket.pk),
            )


        elif action == "reject":

            reason = request.POST.get(
                "rejection_reason",
                ""
            )

            access_request.authorization_status = (
                SystemAccessRequest.AuthorizationStatus.REJECTED
            )

            access_request.save()


            if document:

                document.validation_status = (
                    AuthorizationDocument.ValidationStatus.REJECTED
                )

                document.validated_by = request.user
                document.validated_at = timezone.now()
                document.rejection_reason = reason
                document.save()


            register_activity(
                request=request,
                action=ActivityLog.ACTION_STATUS,
                module="Tickets",
                description=(
                    f"Se rechazó solicitud de acceso "
                    f"{access_request.requested_system}. "
                    f"Motivo: {reason}"
                ),
                object_type="Ticket",
                object_id=str(ticket.pk),
            )


        return redirect(
            "tickets:ticket_detail",
            pk=ticket.pk,
        )


    return redirect(
        "tickets:ticket_detail",
        pk=ticket.pk,
    )
@login_required
@require_POST
def generate_authorization_form_view(request, pk):

    ticket = get_object_or_404(
        Ticket,
        pk=pk,
    )
    require_ticket_view_access(request.user, ticket)

    access_request = get_object_or_404(
        SystemAccessRequest,
        ticket=ticket,
    )

    generated_form = generate_authorization_pdf(
        access_request,
        request.user,
    )

    register_activity(
        request=request,
        action=ActivityLog.ACTION_CREATE,
        module="Tickets",
        description=(
            f"Se generó el formulario de autorización "
            f"{generated_form.original_name}."
        ),
        object_type="Ticket",
        object_id=str(ticket.pk),
    )

    return FileResponse(
        generated_form.file.open("rb"),
        as_attachment=True,
        filename=generated_form.original_name,
    )
