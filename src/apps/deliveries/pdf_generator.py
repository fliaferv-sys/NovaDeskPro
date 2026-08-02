from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

from apps.institution.models import InstitutionSettings


def _image_flowable(image_field, max_width=500, max_height=75):
    """Construye una imagen ajustada sin depender del almacenamiento local."""
    try:
        image_field.open("rb")
        image_data = BytesIO(image_field.read())
        image_field.close()
        width, height = ImageReader(image_data).getSize()
        scale = min(max_width / width, max_height / height, 1)
        image_data.seek(0)
        result = Image(image_data, width=width * scale, height=height * scale)
        result.hAlign = "CENTER"
        return result
    except (AttributeError, OSError, ValueError):
        return None



# ======================================================
# PDF AGRUPADO FINAL PRO
# ======================================================

def generate_delivery_batch_pdf(batch):

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20,
        rightMargin=20,
        topMargin=30,
        bottomMargin=30,
    )

    styles = getSampleStyleSheet()
    elements = []

    institution = InstitutionSettings.get_active()
    institution_name = (
        institution.institution_name if institution else "Petróleos Paraguayos"
    )
    department_name = (
        institution.department_name
        if institution
        else "Dirección de Tecnología de la Información"
    )
    primary_color = institution.primary_color if institution else "#1f3c88"
    footer_text = (
        institution.footer_text
        if institution and institution.footer_text
        else "Documento generado automáticamente por NovaDesk Pro"
    )

    azul = colors.HexColor(primary_color)
    celeste = colors.HexColor("#e7f0fb")
    gris = colors.HexColor("#9ca3af")

    # =========================
    # HEADER PROFESIONAL
    # =========================

    if not institution or institution.show_header_in_pdf:
        header_image = None
        uses_full_header_image = False
        if institution and institution.header_image:
            header_image = _image_flowable(institution.header_image)
            uses_full_header_image = header_image is not None
        elif institution and institution.show_logo_in_pdf and institution.logo:
            header_image = _image_flowable(
                institution.logo,
                max_width=180,
                max_height=55,
            )

        if header_image:
            elements.append(header_image)
            elements.append(Spacer(1, 6))

        # Una imagen de encabezado completa reemplaza los textos para no duplicarlos.
        if not uses_full_header_image:
            elements.append(Paragraph(
                "<para align='center'><b><font size=11 color='{}'>{}</font></b></para>".format(
                    primary_color,
                    escape(institution_name),
                ),
                styles["Normal"]
            ))
            elements.append(Paragraph(
                "<para align='center'><font size=9 color='#6b7280'>{}</font></para>".format(
                    escape(department_name),
                ),
                styles["Normal"]
            ))
            elements.append(Spacer(1, 6))

        linea = Table([[""]], colWidths=[540])
        linea.setStyle(TableStyle([
            ("LINEABOVE", (0, 0), (-1, -1), 2, azul),
        ]))
        elements.append(linea)
        elements.append(Spacer(1, 8))

    elements.append(Paragraph(
        "<para align='center'><b><font size=15 color='{}'>ACTA DE ENTREGA DE ACTIVOS INFORMÁTICOS</font></b></para>".format(primary_color),
        styles["Normal"]
    ))

    elements.append(Spacer(1, 10))

    # =========================
    # INFO
    # =========================

    info = [[
        "Fecha:", batch.delivery_date.strftime("%d/%m/%Y"),
        "Estado:", batch.get_status_display(),
        "Cantidad:", f"{batch.movements.count()} activo(s)"
    ]]

    t_info = Table(info, colWidths=[80, 90, 90, 90, 90, 100])

    t_info.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), celeste),
        ("GRID", (0, 0), (-1, -1), 0.8, gris),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
    ]))

    elements.append(t_info)
    elements.append(Spacer(1, 15))

    # =========================
    # ACTIVOS
    # =========================

    elements.append(Paragraph(
        "<b><font color='{}'>Activos incluidos en la entrega</font></b>".format(primary_color),
        styles["Heading3"]
    ))

    data = [["N°", "Tipo", "Marca / modelo", "N° de Serie", "Nombre / Equipo", "Patrimonio"]]

    for i, m in enumerate(batch.movements.all(), start=1):
        a = m.asset

        data.append([
            str(i),
            a.get_asset_type_display(),
            f"{a.brand or ''} {a.model or ''}",
            a.serial_number or "-",
            a.internal_code
        ])

    table = Table(data, colWidths=[35, 100, 90, 90, 110, 130])

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), azul),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.6, gris),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, celeste]),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 20))

    # =========================
    # ORIGEN
    # =========================

    elements.append(Paragraph(
        "<b><font color='{}'>Origen y responsable de entrega</font></b>".format(primary_color),
        styles["Heading3"]
    ))

    responsable = batch.delivery_responsible.get_full_name()

    tabla_origen = Table([
        ["Funcionario", responsable, "Unidad", "DTI"],
        ["Departamento", batch.department or "-", "Área", "-"],
        ["Sección", "-", "Cargo", "-"],
    ], colWidths=[80, 95, 55, 95])

    tabla_origen.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), celeste),
        ("GRID", (0, 0), (-1, -1), 0.6, gris),
    ]))

    firma_origen = Table([
        ["________________________"],
        [Paragraph(f"<para alignment='center'><b>{responsable}</b></para>", styles["Normal"])],
        ["Firma del responsable de entrega"],
    ], colWidths=[320])

    firma_origen.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))

    contenedor_origen = Table([[tabla_origen, firma_origen]], colWidths=[220, 340])

    contenedor_origen.setStyle(TableStyle([
        ("LEFTPADDING", (1, 0), (1, 0), 60),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    elements.append(contenedor_origen)
    elements.append(Spacer(1, 25))

    # =========================
    # DESTINO
    # =========================

    elements.append(Paragraph(
        "<b><font color='{}'>Destino y responsable receptor</font></b>".format(primary_color),
        styles["Heading3"]
    ))

    receptor = batch.recipient.get_full_name() if batch.recipient else "Sin receptor"

    tabla_destino = Table([
        ["Funcionario", receptor, "Unidad", "-"],
        ["Departamento", batch.department or "-", "Área", "-"],
        ["Sección", "-", "Cargo", "-"],
    ], colWidths=[80, 95, 55, 95])

    tabla_destino.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), celeste),
        ("GRID", (0, 0), (-1, -1), 0.6, gris),
    ]))

    firma_destino = Table([
        ["________________________"],
        [Paragraph(f"<para alignment='center'><b>{receptor}</b></para>", styles["Normal"])],
        ["Firma del responsable receptor"],
    ], colWidths=[250])

    firma_destino.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))

    contenedor_destino = Table([[tabla_destino, firma_destino]], colWidths=[220, 340])

    contenedor_destino.setStyle(TableStyle([
        ("LEFTPADDING", (1, 0), (1, 0), 90),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    elements.append(contenedor_destino)
    elements.append(Spacer(1, 80))

    # =========================
    # DIRECTOR
    # =========================

    firma_director = Table([
        ["______________________________"],
        [institution.director_name if institution and institution.director_name else "Director responsable"],
        [department_name],
    ], colWidths=[300])

    firma_director.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))

    elements.append(firma_director)
    elements.append(Spacer(1, 20))

    # =========================
    # OBSERVACIONES
    # =========================

    observaciones = Table([
        [
            Paragraph("<b>Observaciones</b>", styles["Normal"]),
            Paragraph(batch.observations or "Sin observaciones", styles["Normal"])
        ]
    ],
    colWidths=[140, 400])

    observaciones.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), celeste),
        ("BACKGROUND", (1, 0), (1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.6, gris),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    elements.append(observaciones)
    elements.append(Spacer(1, 12))

    # =========================
    # PIE
    # =========================

    elements.append(Paragraph(
        "<para align='center'><font size=8 color='#6b7280'>{}</font></para>".format(
            escape(footer_text)
        ),
        styles["Normal"]
    ))

    elements.append(Paragraph(
        "<para align='center'><font size=7 color='#9ca3af'>Registrado por: {}</font></para>".format(
            batch.created_by.get_full_name() if batch.created_by else "-"
        ),
        styles["Normal"]
    ))

    doc.build(elements)
    buffer.seek(0)

    return buffer
