"""Registro di carico e scarico export (PDF in EA/EB column layout, XLSX)."""

import io

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HEADERS = ["N.", "Data reg.", "Data evento", "Mov.", "Causale", "Specie / descrizione", "Q.tà", "Marcatura",
           "Documento CITES", "Provenienza / destinazione", "Rif. carico", "Note"]


def _row(e):
    return [
        str(e.number),
        timezone.localtime(e.recorded_at).strftime("%d/%m/%Y"),
        e.event_date.strftime("%d/%m/%Y"),
        e.get_direction_display(),
        e.get_cause_display(),
        f"{e.species.scientific_name} – {e.description}",
        str(e.quantity),
        e.marking,
        e.document,
        e.counterparty,
        str(e.carico_ref.number) if e.carico_ref else "",
        e.notes,
    ]


def register_pdf(keeper, register_type, entries) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm,
                            topMargin=10 * mm, bottomMargin=10 * mm,
                            title=f"Registro {register_type} – {keeper}")
    cell = ParagraphStyle("c", fontName="Helvetica", fontSize=7, leading=8.5)
    head = ParagraphStyle("h", parent=cell, fontName="Helvetica-Bold")
    title = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=12, leading=15)
    data = [[Paragraph(h, head) for h in HEADERS]]
    for e in entries:
        data.append([Paragraph(str(v or ""), cell) for v in _row(e)])
    widths = [10, 17, 17, 14, 22, 45, 10, 35, 35, 40, 12, 20]
    table = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story = [
        Paragraph(f"Registro di carico e scarico {register_type} (D.M. 8 gennaio 2002)", title),
        Paragraph(f"Detentore: {keeper} – {keeper.full_address} – C.F. {keeper.fiscal_code}", cell),
        Spacer(1, 4 * mm),
        table,
    ]
    doc.build(story)
    return buf.getvalue()


def register_xlsx(keeper, register_type, entries) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = f"Registro {register_type}"
    ws.append([f"Registro {register_type} – {keeper}"])
    ws.append(HEADERS)
    for c in ws[2]:
        c.font = Font(bold=True)
    for e in entries:
        ws.append(_row(e))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
