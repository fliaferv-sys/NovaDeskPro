from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.institution.models import InstitutionSettings
from .pdf_generator import _image_flowable


def _text(value, default="-"):
    value = str(value).strip() if value is not None else ""
    return escape(value or default)


def _name(user, default="-"):
    if not user:
        return default
    return user.get_full_name().strip() or user.get_username()


def _section(title, width, primary, style):
    result = Table([[Paragraph(_text(title), style)]], colWidths=[width])
    result.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), .7, primary),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f8fc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return result


def _signature(name, label, width, styles):
    result = Table([
        [""],
        [Paragraph("____________________________", styles["center_small"])],
        [Paragraph(f"<b>{_text(name)}</b>", styles["center_small"])],
        [Paragraph(_text(label), styles["center_tiny"])],
    ], colWidths=[width], rowHeights=[9 * mm, None, None, None])
    result.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return result


def _people_box(rows, signer, signature_label, width, palette, styles):
    detail_rows = [[
        Paragraph(_text(a), styles["label"]), Paragraph(_text(b), styles["value"]),
        Paragraph(_text(c), styles["label"]), Paragraph(_text(d), styles["value"]),
    ] for a, b, c, d in rows]
    detail_width = 340
    details = Table(detail_rows, colWidths=[61, 98, 49, 132])
    details.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), .35, palette["grid"]),
        ("BACKGROUND", (0, 0), (0, -1), palette["label_bg"]),
        ("BACKGROUND", (2, 0), (2, -1), palette["label_bg"]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    result = Table(
        [[details, _signature(signer, signature_label, width - detail_width, styles)]],
        colWidths=[detail_width, width - detail_width],
    )
    result.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), .7, palette["primary"]),
        ("LINEBEFORE", (1, 0), (1, 0), .5, palette["grid"]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return result


def generate_delivery_batch_pdf(batch):
    buffer = BytesIO()
    page_width, _ = A4
    margin = 16 * mm
    width = page_width - 2 * margin
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=margin, rightMargin=margin,
        topMargin=10 * mm, bottomMargin=11 * mm,
        title=f"Acta de entrega {batch.batch_number}", author="NovaDesk Pro",
    )
    institution = InstitutionSettings.get_active()
    institution_name = institution.institution_name if institution else "Petróleos Paraguayos"
    department_name = institution.department_name if institution else "Dirección de Tecnología de la Información"
    primary_hex = institution.primary_color if institution else "#1f3c88"
    primary = colors.HexColor(primary_hex)
    footer = institution.footer_text if institution and institution.footer_text else "Documento generado automáticamente por NovaDesk Pro."
    document_code = institution.document_code if institution else "TI-ACT-001"
    director = institution.director_name if institution and institution.director_name else "Director del Departamento DTI"
    palette = {
        "primary": primary, "grid": colors.HexColor("#9aabc1"),
        "label_bg": colors.HexColor("#edf3fa"), "row_bg": colors.HexColor("#f7f9fc"),
        "table_header_bg": colors.HexColor("#dbe8f7"),
        "muted": colors.HexColor("#667085"),
    }
    base = getSampleStyleSheet()
    styles = {
        "tiny": ParagraphStyle("v2tiny", parent=base["Normal"], fontSize=5.3, leading=6.5),
        "small": ParagraphStyle("v2small", parent=base["Normal"], fontSize=6.2, leading=7.5),
        "center_small": ParagraphStyle("v2cs", parent=base["Normal"], fontSize=6.2, leading=7.5, alignment=TA_CENTER),
        "center_tiny": ParagraphStyle("v2ct", parent=base["Normal"], fontSize=5.3, leading=6.4, alignment=TA_CENTER, textColor=palette["muted"]),
        "label": ParagraphStyle("v2label", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=6, leading=7.2),
        "value": ParagraphStyle("v2value", parent=base["Normal"], fontSize=6, leading=7.2),
        "section": ParagraphStyle("v2section", parent=base["Normal"], fontName="Helvetica-BoldOblique", fontSize=7.4, leading=9, textColor=primary),
        "title": ParagraphStyle("v2title", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=12.5, leading=15, alignment=TA_CENTER, textColor=primary),
        "institution": ParagraphStyle("v2inst", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8.5, leading=10, alignment=TA_CENTER, textColor=primary),
        "department": ParagraphStyle("v2dept", parent=base["Normal"], fontSize=6.2, leading=7.5, alignment=TA_CENTER, textColor=palette["muted"]),
        "meta": ParagraphStyle("v2meta", parent=base["Normal"], fontSize=5.5, leading=6.5, alignment=TA_CENTER, textColor=palette["muted"]),
    }
    elements = []

    if not institution or institution.show_header_in_pdf:
        header = None
        logo = None
        if institution and institution.header_image:
            header = _image_flowable(institution.header_image, width, 22 * mm)
        elif institution and institution.show_logo_in_pdf and institution.logo:
            logo = _image_flowable(institution.logo, 40 * mm, 12 * mm)
        if header:
            elements.extend([header, Spacer(1, 1.5 * mm)])
        else:
            if logo:
                elements.extend([logo, Spacer(1, .7 * mm)])
            elements.append(Paragraph(_text(institution_name), styles["institution"]))
            elements.append(Paragraph(_text(department_name), styles["department"]))
            elements.append(Spacer(1, 1 * mm))

    elements.append(Paragraph("ACTA DE ENTREGA DE ACTIVOS INFORMÁTICOS", styles["title"]))
    elements.append(Paragraph(
        "{} · Código: {} · Movimiento agrupado: {}".format(
            _text(institution.institution_short_name if institution else "PETROPAR"),
            _text(document_code), _text(batch.batch_number)), styles["meta"]))
    elements.append(Spacer(1, 1.5 * mm))

    info = Table([[
        Paragraph("<b>Fecha:</b> " + batch.delivery_date.strftime("%d/%m/%Y"), styles["small"]),
        Paragraph("<b>Estado:</b> " + _text(batch.get_status_display()), styles["small"]),
        Paragraph(f"<b>Cantidad:</b> {batch.movements.count()} activo(s)", styles["small"]),
    ]], colWidths=[width * .34, width * .33, width * .33])
    info.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), .6, palette["grid"]), ("INNERGRID", (0, 0), (-1, -1), .35, palette["grid"]),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.extend([info, Spacer(1, 2 * mm), _section("Activos incluidos en la entrega", width, primary, styles["section"])])

    headers = ["N.º", "Tipo", "Marca / modelo", "Número de serie", "Patrimonio", "Código interno", "Hostname"]
    asset_rows = [[Paragraph(f"<b>{_text(item)}</b>", styles["tiny"]) for item in headers]]
    for number, movement in enumerate(batch.movements.all(), 1):
        asset = movement.asset
        asset_rows.append([
            Paragraph(str(number), styles["tiny"]), Paragraph(_text(asset.get_asset_type_display()), styles["tiny"]),
            Paragraph(_text(" ".join(filter(None, [asset.brand, asset.model]))), styles["tiny"]),
            Paragraph(_text(asset.serial_number), styles["tiny"]), Paragraph(_text(asset.patrimonial_code), styles["tiny"]),
            Paragraph(_text(asset.internal_code), styles["tiny"]), Paragraph(_text(asset.hostname), styles["tiny"]),
        ])
    asset_table = Table(asset_rows, colWidths=[24, 54, 105, 74, 70, 106, width - 433], repeatRows=1)
    asset_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), palette["table_header_bg"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), primary),
        ("GRID", (0, 0), (-1, -1), .35, palette["grid"]),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, palette["row_bg"]]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.extend([asset_table, Spacer(1, 2 * mm)])

    responsible = _name(batch.delivery_responsible)
    origin = [
        ("Origen", institution.institution_short_name if institution else "PETROPAR", "Unidad", batch.origin_unit),
        ("Departamento", batch.origin_department, "Área", batch.origin_area),
        ("Sección", batch.origin_section, "Cargo", batch.origin_position),
        ("Funcionario", responsible, "Legajo", batch.origin_employee_number),
    ]
    elements.extend([
        _section("Origen y responsable de entrega", width, primary, styles["section"]),
        _people_box(origin, responsible, "Firma del responsable de entrega", width, palette, styles), Spacer(1, 2 * mm),
    ])
    recipient = _name(batch.recipient, "Sin receptor asignado")
    destination = [
        ("Destino", "{} - {}".format(batch.destination_branch or "-", batch.location or "-"), "Unidad", batch.recipient_unit),
        ("Departamento", batch.department, "Área", batch.recipient_area),
        ("Sección", batch.recipient_section, "Cargo", batch.recipient_position),
        ("Funcionario", recipient, "Legajo", batch.recipient_employee_number),
    ]
    elements.extend([
        _section("Destino y responsable receptor", width, primary, styles["section"]),
        _people_box(destination, recipient, "Firma del responsable receptor", width, palette, styles), Spacer(1, 3 * mm),
    ])

    director_box = Table([[_signature(director, department_name, 88 * mm, styles)]], colWidths=[width])
    director_box.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    elements.extend([director_box, Spacer(1, 2 * mm)])
    observations = Table([[
        Paragraph("<b>Observaciones</b>", styles["small"]),
        Paragraph(_text(batch.observations, "Sin observaciones"), styles["small"]),
    ]], colWidths=[85, width - 85])
    observations.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), .5, palette["grid"]), ("LINEAFTER", (0, 0), (0, 0), .35, palette["grid"]),
        ("BACKGROUND", (0, 0), (0, 0), palette["label_bg"]), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.extend([observations, Spacer(1, 1.5 * mm), Paragraph(
        "{} · Registrado por: {}".format(_text(footer), _text(_name(batch.created_by))), styles["center_tiny"])])

    def page_number(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 5.5)
        canvas.setFillColor(palette["muted"])
        canvas.drawRightString(page_width - margin, 6 * mm, f"Página {document.page}")
        canvas.restoreState()

    doc.build(elements, onFirstPage=page_number, onLaterPages=page_number)
    buffer.seek(0)
    return buffer
