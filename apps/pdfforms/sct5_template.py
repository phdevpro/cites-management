"""Blank Modello SCT5 (comunicazione di decesso, All. A) generated from code.

Layout and wording follow the official ministry form. Field names match the official
fillable PDF ("Campo di testo 7_*") so already-filled SCT5 files can still be imported.
"""

import io
from functools import lru_cache

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

W, H = A4

# name -> (x1, y1, x2, y2, multiline), same rectangles as the official form
FIELDS = {
    "Campo di testo 7": (396, 719, 568, 746, True),
    "Campo di testo 7_2": (121, 618, 529, 629, False),
    "Campo di testo 7_3": (87, 598, 292, 608, False),
    "Campo di testo 7_9": (326, 598, 346, 609, False),
    "Campo di testo 7_8": (366, 598, 472, 609, False),
    "Campo di testo 7_4": (101, 578, 292, 588, False),
    "Campo di testo 7_10": (326, 578, 346, 588, False),
    "Campo di testo 7_7": (367, 578, 473, 588, False),
    "Campo di testo 7_5": (81, 558, 292, 568, False),
    "Campo di testo 7_6": (355, 558, 532, 568, False),
    "Campo di testo 7_11": (59, 442, 172, 453, False),
    "Campo di testo 7_12": (180, 442, 293, 453, False),
    "Campo di testo 7_13": (301, 442, 414, 453, False),
    "Campo di testo 7_14": (422, 442, 534, 453, False),
    "Campo di testo 7_15": (59, 423, 172, 434, False),
    "Campo di testo 7_16": (180, 423, 293, 434, False),
    "Campo di testo 7_17": (301, 423, 414, 434, False),
    "Campo di testo 7_18": (422, 423, 534, 434, False),
    "Campo di testo 7_19": (108, 320, 221, 331, False),
}

NOTE = (
    "La presente è resa nella consapevolezza delle sanzioni penali previste nel caso di dichiarazioni mendaci, "
    "richiamate all'articolo 76 del DPR 445/2000. Ai sensi dell'articolo 38 del DPR 445/2000, la presente è "
    "sottoscritta dall'interessato in presenza del dipendente addetto ovvero sottoscritta o inviata, insieme alla "
    "fotocopia non autenticata di un documento di identità, via fax, a mezzo posta ovvero tramite incaricato"
)
DECLARATION = (
    "consapevole delle sanzioni penali, nel caso di dichiarazioni non veritiere, di formazione o uso di atti falsi, "
    "richiamate dall'art. 76 del D.P.R. 445 del 28 dicembre 2000,"
)
RETURN_TEXT = (
    "in allegato alla presente i certificati, conformi ai formulari di cui al reg. (CE) 865/2006, annotati nella "
    "precedente tabella e relativi ai corrispondenti esemplari deceduti."
)


def _para(c, text, x, y, width, font="Helvetica", size=8, leading=10):
    c.setFont(font, size)
    for line in simpleSplit(text, font, size, width):
        c.drawString(x, y, line)
        y -= leading
    return y


def _center(c, text, y, font="Helvetica-Bold", size=8.5):
    c.setFont(font, size)
    c.drawCentredString(W / 2, y, text)


@lru_cache(maxsize=1)
def build_sct5() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("Modello SCT5")
    c.setLineWidth(0.6)

    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(570, 805, "MODELLO SCT5")

    # office boxes
    c.rect(25, 700, 225, 75)
    c.setFont("Helvetica", 7.5)
    c.drawString(62, 765, "spazio riservato all’ufficio")
    c.rect(385, 700, 190, 75)
    c.drawString(390, 765, "Al Servizio CITES Territoriale")
    c.drawString(390, 756, "Carabinieri di")

    _center(c, "COMUNICAZIONE DELL’AVVENUTO DECESSO DI ESEMPLARI VIVI DI ANIMALI E PIANTE", 680)
    _center(c, "DI SPECIE DELL'ALLEGATO \"A\" DEL REG. (CE) 338/97", 670)
    _center(c, "(articolo 5, comma 2, della legge 150/1992)", 660, "Helvetica", 7.5)

    c.setFont("Helvetica", 8)
    labels = [
        (40, 620, "Il/la sottoscritto/a"),
        (40, 600, "nato a"), (298, 600, "Prov. ("), (348, 600, ") il"),
        (40, 580, "residente a"), (298, 580, "Prov. ("), (348, 580, ") tel"),
        (40, 560, "in Via"), (297, 560, "doc. identità n."),
    ]
    for x, y, text in labels:
        c.drawString(x, y, text)
    _para(c, DECLARATION, 40, 538, 520)

    _center(c, "COMUNICA", 500)
    c.setFont("Helvetica", 8)
    c.drawCentredString(W / 2, 482, "il decesso dei seguenti esemplari :")

    # table
    cols = [55, 176, 297, 418, 539]
    top, header_bottom, bottom = 474, 456, 418
    c.rect(cols[0], bottom, cols[-1] - cols[0], top - bottom)
    c.line(cols[0], header_bottom, cols[-1], header_bottom)
    c.line(cols[0], 437.5, cols[-1], 437.5)
    for x in cols[1:-1]:
        c.line(x, bottom, x, top)
    c.setFont("Helvetica", 7.5)
    c.drawString(cols[0] + 3, 465, "Nome scientifico")
    c.drawString(cols[1] + 3, 465, "Nome comune")
    c.drawString(cols[2] + 3, 465, "Marcatura")
    c.setFont("Helvetica", 6)
    c.drawString(cols[2] + 36, 465, "(se presente)")
    c.setFont("Helvetica", 7.5)
    c.drawString(cols[3] + 3, 467, "Certificato o altro Documento")
    c.drawString(cols[3] + 3, 459, "CITES")

    _center(c, "RESTITUISCE", 395)
    _para(c, RETURN_TEXT, 40, 375, 520)

    c.setFont("Helvetica", 8)
    c.drawString(40, 323, "Luogo e data")
    c.drawString(420, 345, "Firma")
    c.line(370, 333, 545, 333)
    c.setFillColor(colors.black)
    _para(c, NOTE, 310, 322, 240, size=5.5, leading=7)

    form = c.acroForm
    for name, (x1, y1, x2, y2, multiline) in FIELDS.items():
        form.textfield(
            name=name, x=x1, y=y1, width=x2 - x1, height=y2 - y1, borderWidth=0.6, borderColor=colors.black,
            fillColor=colors.white, textColor=colors.black, forceBorder=True, fontName="Helvetica",
            fontSize=6, fieldFlags="multiline" if multiline else "", value="",
        )
    c.showPage()
    c.save()
    return buf.getvalue()
