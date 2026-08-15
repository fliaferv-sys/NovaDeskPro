from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.institution.models import InstitutionSettings


def _text(value, default="-"):
    value = str(value).strip() if value is not None else ""
    return escape(value or default)


def generate_stock_delivery_pdf(delivery):
    buffer = BytesIO()
    institution = InstitutionSettings.get_active()
    primary = colors.HexColor(institution.primary_color if institution else "#1f3c88")
    institution_name = institution.institution_name if institution else "NovaDesk Pro"
    footer = institution.footer_text if institution and institution.footer_text else "Documento generado por NovaDesk Pro."
    styles = getSampleStyleSheet()
    title = ParagraphStyle("stock-title", parent=styles["Title"], alignment=TA_CENTER, textColor=primary, fontSize=14)
    small = ParagraphStyle("stock-small", parent=styles["Normal"], fontSize=8, leading=10)
    centered = ParagraphStyle("stock-center", parent=small, alignment=TA_CENTER)
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=12 * mm, title=f"Acta {delivery.number}", pageCompression=0)
    elements = []
    if institution and institution.show_logo_in_pdf and institution.logo:
        try:
            logo = Image(institution.logo.path)
            logo._restrictSize(42 * mm, 14 * mm)
            elements.extend([logo, Spacer(1, 1 * mm)])
        except (OSError, ValueError):
            pass
    elements.extend([
        Paragraph(_text(institution_name), centered),
        Spacer(1, 2 * mm),
        Paragraph("ACTA DE ENTREGA DE INSUMOS", title),
        Paragraph(f"<b>Número:</b> {_text(delivery.number)} &nbsp;&nbsp; <b>Fecha:</b> {delivery.delivery_date:%d/%m/%Y}", centered),
        Spacer(1, 5 * mm),
    ])
    info = [
        ["Receptor", delivery.recipient_name, "Departamento", delivery.department_name],
        ["Sede", str(delivery.branch), "Ubicación", delivery.location.full_path if delivery.location else "-"],
        ["Entregado por", str(delivery.delivery_responsible), "Autorizado por", str(delivery.authorized_by or "-")],
    ]
    info_table = Table([[Paragraph(f"<b>{_text(a)}</b>", small), Paragraph(_text(b), small), Paragraph(f"<b>{_text(c)}</b>", small), Paragraph(_text(d), small)] for a, b, c, d in info], colWidths=[25 * mm, 58 * mm, 28 * mm, 69 * mm])
    info_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .4, colors.grey), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#edf3fa")), ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#edf3fa")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    elements.extend([info_table, Spacer(1, 5 * mm)])
    rows = [["Cantidad", "Unidad", "Código/SKU", "Producto", "Marca/Modelo", "Ubicación de origen"]]
    for line in delivery.lines.select_related("source_location"):
        rows.append([str(line.quantity), line.product_unit, line.product_sku, line.product_name, line.product_brand_model or "-", line.source_location.full_path])
    table = Table([[Paragraph(f"<b>{_text(cell)}</b>", small) if index == 0 else Paragraph(_text(cell), small) for cell in row] for index, row in enumerate(rows)], colWidths=[15 * mm, 22 * mm, 28 * mm, 43 * mm, 35 * mm, 37 * mm], repeatRows=1)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe8f7")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    elements.extend([table, Spacer(1, 5 * mm), Paragraph(f"<b>Observaciones:</b> {_text(delivery.observations, 'Sin observaciones')}", small), Spacer(1, 14 * mm)])
    signatures = Table([["________________________", "________________________", "________________________"], ["Entregado por", "Recibido por", "Autorizador"]], colWidths=[60 * mm] * 3)
    signatures.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
    elements.extend([signatures, Spacer(1, 6 * mm), Paragraph(_text(footer), centered)])
    doc.build(elements)
    buffer.seek(0)
    return buffer
