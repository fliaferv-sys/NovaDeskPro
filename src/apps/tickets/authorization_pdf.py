from io import BytesIO

from django.core.files.base import ContentFile
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from .models import GeneratedAuthorizationForm


def _draw_checkbox(pdf, x, y, checked=False):
    size = 4 * mm

    pdf.rect(
        x,
        y,
        size,
        size,
        stroke=1,
        fill=0,
    )

    if checked:
        pdf.setLineWidth(1.5)
        pdf.line(
            x + 1 * mm,
            y + 2 * mm,
            x + 2 * mm,
            y + 1 * mm,
        )
        pdf.line(
            x + 2 * mm,
            y + 1 * mm,
            x + 3.5 * mm,
            y + 3.5 * mm,
        )

    return size


def _draw_line_field(pdf, label, value, x, y, width):
    pdf.setFont("Helvetica", 8)
    pdf.drawString(x, y, label)

    label_width = pdf.stringWidth(
        label,
        "Helvetica",
        8,
    )

    line_start = x + label_width + 2 * mm

    pdf.line(
        line_start,
        y - 1 * mm,
        x + width,
        y - 1 * mm,
    )

    if value:
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(
            line_start + 1 * mm,
            y,
            str(value),
        )


def _draw_section(pdf, title, x, y, width, height):
    pdf.roundRect(
        x,
        y - height,
        width,
        height,
        6 * mm,
        stroke=1,
        fill=0,
    )

    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(
        x + 5 * mm,
        y - 6 * mm,
        title,
    )


def generate_authorization_pdf(access_request, user):
    buffer = BytesIO()

    pdf = canvas.Canvas(
        buffer,
        pagesize=A4,
    )

    page_width, page_height = A4

    ticket = access_request.ticket
    requester = ticket.requester

    margin_x = 18 * mm
    content_width = page_width - (margin_x * 2)

    current_y = page_height - 18 * mm

    # ======================================================
    # ENCABEZADO
    # ======================================================

    pdf.setTitle(
        f"Formulario ABM - {ticket.ticket_number}"
    )

    pdf.setFont("Helvetica-Bold", 15)

    title_style = ParagraphStyle(
        name="Title",
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=16,
        alignment=TA_CENTER,
    )

    title = Paragraph(
        "Formulario de Alta, Baja y Modificacion de Usuarios",
        title_style,
    )

    title_width = content_width - 30 * mm

    title.wrapOn(
        pdf,
        title_width,
        30 * mm,
    )

    title.drawOn(
        pdf,
        margin_x + 30 * mm,
        current_y - 12 * mm,
    )

    pdf.setFont("Helvetica", 8)
    pdf.drawString(
        margin_x,
        current_y - 18 * mm,
        "NovaDesk Pro",
    )

    pdf.drawRightString(
        page_width - margin_x,
        current_y - 18 * mm,
        f"Ticket: {ticket.ticket_number}",
    )

    current_y -= 27 * mm

    # ======================================================
    # FECHA Y TIPO DE SOLICITUD
    # ======================================================

    request_date = timezone.localdate().strftime(
        "%d/%m/%Y"
    )

    _draw_line_field(
        pdf,
        "Fecha de solicitud:",
        request_date,
        margin_x,
        current_y,
        65 * mm,
    )

    pdf.setFont("Helvetica", 9)
    pdf.drawString(
        margin_x + 75 * mm,
        current_y,
        "Tipo de solicitud:",
    )

    checkbox_y = current_y - 3 * mm
    checkbox_x = margin_x + 105 * mm

    operations = [
        (
            "Alta",
            access_request.operation
            == access_request.RequestOperation.USER_CREATION,
        ),
        (
            "Baja",
            access_request.operation
            == access_request.RequestOperation.USER_DELETION,
        ),
        (
            "Modificación",
            access_request.operation
            == access_request.RequestOperation.USER_MODIFICATION,
        ),
    ]

    for label, checked in operations:
        size = _draw_checkbox(
            pdf,
            checkbox_x,
            checkbox_y,
            checked,
        )

        pdf.setFont("Helvetica", 8)
        pdf.drawString(
            checkbox_x + size + 2 * mm,
            current_y,
            label,
        )

        checkbox_x += 28 * mm

    current_y -= 10 * mm

    # ======================================================
    # DATOS DEL SOLICITANTE
    # ======================================================

    section_height = 48 * mm

    _draw_section(
        pdf,
        "Datos del solicitante",
        margin_x,
        current_y,
        content_width,
        section_height,
    )

    section_x = margin_x + 6 * mm
    row_y = current_y - 14 * mm
    half_width = (content_width - 16 * mm) / 2

    _draw_line_field(
        pdf,
        "Nombres:",
        requester.first_name,
        section_x,
        row_y,
        half_width,
    )

    _draw_line_field(
        pdf,
        "Apellidos:",
        requester.last_name,
        section_x + half_width + 4 * mm,
        row_y,
        half_width,
    )

    row_y -= 9 * mm

    _draw_line_field(
        pdf,
        "Cédula:",
        requester.document_number or "",
        section_x,
        row_y,
        half_width,
    )

    _draw_line_field(
        pdf,
        "Celular:",
        requester.phone or "",
        section_x + half_width + 4 * mm,
        row_y,
        half_width,
    )

    row_y -= 9 * mm

    _draw_line_field(
        pdf,
        "Dependencia:",
        requester.department or "",
        section_x,
        row_y,
        half_width,
    )

    _draw_line_field(
        pdf,
        "Función:",
        requester.position or "",
        section_x + half_width + 4 * mm,
        row_y,
        half_width,
    )

    row_y -= 9 * mm

    _draw_line_field(
        pdf,
        "Usuario Windows:",
        requester.username,
        section_x,
        row_y,
        half_width,
    )

    _draw_line_field(
        pdf,
        "Legajo:",
        requester.employee_number or "",
        section_x + half_width + 4 * mm,
        row_y,
        half_width,
    )

    current_y -= section_height + 5 * mm

    # ======================================================
    # DATOS SAP
    # ======================================================

    sap_section_height = 52 * mm

    _draw_section(
        pdf,
        "Datos del usuario y acceso solicitado",
        margin_x,
        current_y,
        content_width,
        sap_section_height,
    )

    row_y = current_y - 14 * mm
    _draw_line_field(
        pdf, "Funcionario:", access_request.affected_employee,
        section_x, row_y, half_width,
    )
    _draw_line_field(
        pdf, "Cedula:", access_request.affected_document_number,
        section_x + half_width + 4 * mm, row_y, half_width,
    )

    row_y -= 9 * mm

    _draw_line_field(
        pdf, "Legajo:", access_request.employee_number,
        section_x, row_y, half_width,
    )
    _draw_line_field(
        pdf, "Correo:", access_request.requested_email,
        section_x + half_width + 4 * mm, row_y, half_width,
    )

    row_y -= 9 * mm

    _draw_line_field(
        pdf, "Sistema:", access_request.requested_system,
        section_x, row_y, half_width,
    )
    _draw_line_field(
        pdf, "Departamento:", access_request.employee_department,
        section_x + half_width + 4 * mm, row_y, half_width,
    )

    row_y -= 9 * mm

    _draw_line_field(
        pdf,
        "Transacciones / permisos:",
        access_request.requested_permissions,
        section_x,
        row_y,
        content_width - 12 * mm,
    )

    row_y -= 13 * mm

    _draw_line_field(
        pdf,
        "Justificación:",
        access_request.justification,
        section_x,
        row_y,
        content_width - 12 * mm,
    )

    current_y -= sap_section_height + 5 * mm

    # ======================================================
    # DATOS DEL AUTORIZANTE
    # ======================================================

    authorization_height = 40 * mm

    _draw_section(
        pdf,
        "Datos del autorizante",
        margin_x,
        current_y,
        content_width,
        authorization_height,
    )

    row_y = current_y - 14 * mm

    _draw_line_field(
        pdf,
        "Nombre y apellido:",
        access_request.authorizing_director,
        section_x,
        row_y,
        content_width - 12 * mm,
    )

    row_y -= 9 * mm

    _draw_line_field(
        pdf,
        "Dependencia:",
        "",
        section_x,
        row_y,
        half_width,
    )

    _draw_line_field(
        pdf,
        "Función:",
        "",
        section_x + half_width + 4 * mm,
        row_y,
        half_width,
    )

    row_y -= 9 * mm

    _draw_line_field(
        pdf,
        "Legajo:",
        "",
        section_x,
        row_y,
        half_width,
    )

    _draw_line_field(
        pdf,
        "Cédula:",
        "",
        section_x + half_width + 4 * mm,
        row_y,
        half_width,
    )

    current_y -= authorization_height + 7 * mm

    # ======================================================
    # FIRMAS
    # ======================================================

    signature_width = 48 * mm
    signature_gap = 12 * mm
    signature_x = margin_x + 5 * mm

    signatures = [
        "Solicitante",
        "Autorizante",
        "Vo.Bo. DTI",
    ]

    for signature in signatures:
        pdf.line(
            signature_x,
            current_y,
            signature_x + signature_width,
            current_y,
        )

        pdf.setFont("Helvetica", 8)
        pdf.drawCentredString(
            signature_x + (signature_width / 2),
            current_y - 5 * mm,
            "Firma y aclaración",
        )

        pdf.drawCentredString(
            signature_x + (signature_width / 2),
            current_y - 10 * mm,
            signature,
        )

        signature_x += signature_width + signature_gap

    current_y -= 18 * mm

    # ======================================================
    # USO EXCLUSIVO DTI
    # ======================================================

    pdf.rect(
        margin_x,
        current_y - 30 * mm,
        content_width,
        30 * mm,
        stroke=1,
        fill=0,
    )

    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(
        margin_x + 3 * mm,
        current_y - 5 * mm,
        "Uso exclusivo de DTI - Detalle del acceso otorgado:",
    )

    pdf.setFont("Helvetica", 8)
    pdf.drawRightString(
        page_width - margin_x - 3 * mm,
        current_y - 5 * mm,
        "Fecha de proceso: ____/____/________",
    )

    for offset in [12, 19]:
        pdf.line(
            margin_x + 4 * mm,
            current_y - offset * mm,
            page_width - margin_x - 4 * mm,
            current_y - offset * mm,
        )

    pdf.showPage()
    pdf.save()

    pdf_content = buffer.getvalue()
    buffer.close()

    next_version = (
        access_request.generated_forms.count() + 1
    )

    file_name = (
        f"{ticket.ticket_number}_"
        f"formulario_ABM_SAP_v{next_version}.pdf"
    )

    generated_form = GeneratedAuthorizationForm(
        access_request=access_request,
        original_name=file_name,
        version=next_version,
        generated_by=user,
    )

    generated_form.file.save(
        file_name,
        ContentFile(pdf_content),
        save=False,
    )

    generated_form.save()

    return generated_form
