from django.contrib.auth.decorators import login_required, permission_required
from django.http import FileResponse
from django.shortcuts import get_object_or_404

from .models import AssetCustodyMovement, DeliveryBatch
from .pdf_generator_v2 import (
    
    generate_delivery_batch_pdf,
)


# ======================================================
# PDF AGRUPADO (NUEVO 🔥)
# ======================================================

@login_required
@permission_required("deliveries.view_deliverybatch", raise_exception=True)
def delivery_batch_pdf_view(request, pk):
    batch = get_object_or_404(
        DeliveryBatch.objects.prefetch_related("movements__asset"),
        pk=pk,
    )

    pdf_buffer = generate_delivery_batch_pdf(batch)

    # 🔥 NOMBRE PROFESIONAL
    filename = f"ACTA-{batch.batch_number}.pdf"

    # 🔥 DETECTAR SI ES DESCARGA
    download = request.GET.get("download")

    return FileResponse(
        pdf_buffer,
        as_attachment=True if download else False,
        filename=filename,
        content_type="application/pdf",
    )
