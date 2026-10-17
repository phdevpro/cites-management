"""Envelope (DL, 220x110 mm) for raccomandata to the CITES office."""

import io

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def envelope_pdf(keeper, office, subject: str = "") -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(220 * mm, 110 * mm))
    c.setFont("Helvetica", 9)
    y = 100 * mm
    for line in [f"Mitt.: {keeper.full_name}", keeper.address, f"{keeper.postal_code} {keeper.city} ({keeper.province})"]:
        c.drawString(10 * mm, y, line.strip())
        y -= 4.5 * mm
    if subject:
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(10 * mm, 12 * mm, f"Oggetto: {subject}"[:110])
    c.setFont("Helvetica-Bold", 12)
    y = 55 * mm
    lines = ["Spett.le", office.name if office else "Servizio CITES Territoriale"]
    if office and office.address:
        lines += [part.strip() for part in office.address.split(" - ")]
    for line in lines:
        c.drawString(110 * mm, y, line)
        y -= 6 * mm
    c.save()
    return buf.getvalue()
