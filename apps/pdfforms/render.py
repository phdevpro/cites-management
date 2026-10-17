"""Render official CITES forms to PDF bytes.

- SCT1A, SCT5: fill the official AcroForm templates (field mapping in MAPPINGS).
- SCT1B: text overlay on the official (non-fillable) template.
- SCT3, CESSB, letters: generated with ReportLab following the official layout.

Rows beyond the template capacity spill onto extra copies of the form.
"""

import io
from pathlib import Path
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, NameObject
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .formdata import FORM_SPECS
from .sct5_template import build_sct5

TEMPLATES = Path(__file__).parent / "templates_pdf"


def template_source(kind: str):
    """Official blank form: shipped PDF, or generated from code (SCT5)."""
    if kind == "SCT5":
        return io.BytesIO(build_sct5())
    return str(TEMPLATES / f"{kind.lower()}.pdf")

# Semantic key → AcroForm field name. Row fields: list per row of column → field name.
MAPPINGS = {
    "SCT1A": {
        "fields": {
            "office": "Campo di testo 4",
            "declarant": "Campo di testo 3",
            "site_address": "Campo di testo 1",
            "domicile": "Campo di testo 1_2",
            "site_phone": "Campo di testo 1_3",
            "father_import": "Campo di testo 2_31",
            "mother_import": "Campo di testo 2_32",
            "father_eucert": "Campo di testo 2_33",
            "mother_eucert": "Campo di testo 2_34",
            "father_marking": "Campo di testo 2_35",
            "mother_marking": "Campo di testo 2_36",
            "other": "Campo di testo 2_37",
            "place_date": "Campo di testo 2_38",
        },
        "rows": [
            dict(zip(["scientific_name", "common_name", "birth_date", "marking_type", "marking_code"],
                     [f"Campo di testo 2{'' if n == 1 else '_' + str(n)}" for n in range(start, start + 5)]))
            for start in (1, 6, 11, 16, 21, 26)
        ],
    },
    "SCT5": {
        "fields": {
            "office_city": "Campo di testo 7",
            "name": "Campo di testo 7_2",
            "birth_place": "Campo di testo 7_3",
            "birth_province": "Campo di testo 7_9",
            "birth_date": "Campo di testo 7_8",
            "city": "Campo di testo 7_4",
            "province": "Campo di testo 7_10",
            "phone": "Campo di testo 7_7",
            "street": "Campo di testo 7_5",
            "id_doc": "Campo di testo 7_6",
            "place_date": "Campo di testo 7_19",
        },
        "rows": [
            dict(zip(["scientific_name", "common_name", "marking", "document"],
                     [f"Campo di testo 7_{n}" for n in range(start, start + 4)]))
            for start in (11, 15)
        ],
    },
}


def _chunks(rows, size):
    rows = rows or []
    if not rows:
        return [[]]
    return [rows[i:i + size] for i in range(0, len(rows), size)]


def _merge(parts: list[bytes]) -> bytes:
    if len(parts) == 1:
        return parts[0]
    writer = PdfWriter()
    for part in parts:
        writer.append(PdfReader(io.BytesIO(part)))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# --------------------------------------------------------------------------- AcroForm

def _fill_acroform(kind: str, data: dict, flatten: bool) -> list[bytes]:
    mapping = MAPPINGS[kind]
    spec = FORM_SPECS[kind]
    pages = []
    for chunk in _chunks(data.get("rows"), spec.rows_per_page):
        values = {}
        for key, field_name in mapping["fields"].items():
            values[field_name] = str(data["fields"].get(key, "") or "")
        for row, row_map in zip(chunk, mapping["rows"]):
            for col, field_name in row_map.items():
                values[field_name] = str(row.get(col, "") or "")
        writer = PdfWriter(clone_from=template_source(kind))
        writer.set_need_appearances_writer(True)
        for page in writer.pages:
            writer.update_page_form_field_values(page, values, auto_regenerate=False, flatten=flatten)
        if flatten:
            writer.remove_annotations(subtypes="/Widget")
            if "/AcroForm" in writer._root_object:
                del writer._root_object[NameObject("/AcroForm")]
        else:
            writer._root_object["/AcroForm"][NameObject("/NeedAppearances")] = BooleanObject(True)
        out = io.BytesIO()
        writer.write(out)
        pages.append(out.getvalue())
    return pages


# --------------------------------------------------------------------------- SCT1B overlay

_H = 841.68


def _overlay_text(c, x, top, text, size=8, width=None, white=True):
    """Write text with its baseline ~top+9 (pdfplumber 'top' coordinates)."""
    if not text:
        return
    c.setFont("Helvetica", size)
    y = _H - top - 9
    if width is None:
        width = c.stringWidth(text, "Helvetica", size) + 2
    while c.stringWidth(text, "Helvetica", size) > width and size > 5:
        size -= 0.5
        c.setFont("Helvetica", size)
    if white:
        c.setFillColor(colors.white)
        c.rect(x - 1, y - 2, width + 2, size + 3, stroke=0, fill=1)
        c.setFillColor(colors.black)
    c.drawString(x, y, text)


def _split_lines(text, n):
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) <= n:
        return lines + [""] * (n - len(lines))
    return lines[: n - 1] + [" ".join(lines[n - 1:])]


def _wrap(text, n, width, size=8):
    from reportlab.lib.utils import simpleSplit

    lines = []
    for para in (text or "").splitlines() or [""]:
        lines.extend(simpleSplit(para, "Helvetica", size, width) or [""])
    lines = [ln for ln in lines if ln.strip()]
    return (lines + [""] * n)[:n]


def _render_sct1b(data: dict) -> list[bytes]:
    spec = FORM_SPECS["SCT1B"]
    f = data["fields"]
    out_pages = []
    col_x = [("scientific_name", 52, 100), ("common_name", 159, 102), ("birth_date", 268, 68),
             ("marking_type", 343, 100), ("marking_code", 449, 116)]
    for chunk in _chunks(data.get("rows"), spec.rows_per_page):
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(595.44, _H))
        _overlay_text(c, 385, 36, f.get("office", ""), 10, 180)
        for i, line in enumerate(_wrap(f.get("declarant", ""), 2, 280)):
            _overlay_text(c, 30, 119 + i * 17, line, 8, 280)
        for i, line in enumerate(_wrap(f.get("site_address", ""), 2, 240)):
            _overlay_text(c, 324, 119 + i * 17, line, 8, 240)
        for i, line in enumerate(_wrap(f.get("domicile", ""), 2, 280)):
            _overlay_text(c, 30, 172 + i * 17, line, 8, 280)
        _overlay_text(c, 324, 172, f.get("site_phone", ""), 8, 240)
        for r, row in enumerate(chunk):
            top = 262 + r * 18.2
            for col, x, w in col_x:
                _overlay_text(c, x, top, str(row.get(col, "") or ""), 7, w, white=False)
        c.setFont("Helvetica-Bold", 11)
        if f.get("art54_yes"):
            c.drawString(30, _H - 472 - 9, "X")
            _overlay_text(c, 176, 470, f.get("art54_date", ""), 8, 120)
            _overlay_text(c, 383, 470, f.get("art54_protocol", ""), 8, 175)
        else:
            c.drawString(30, _H - 490 - 9, "X")
        for key, top, mark_top in (("parents_import", 546, 532), ("parents_eucert", 580, 565),
                                   ("parents_marking", 613, 598), ("other", 646, 632)):
            if f.get(key):
                c.setFont("Helvetica-Bold", 11)
                c.drawString(30, _H - mark_top - 9, "X")
                _overlay_text(c, 30, top, f[key], 8, 535)
        _overlay_text(c, 88, 672, f.get("place_date", ""), 9, 180)
        c.save()
        writer = PdfWriter(clone_from=str(TEMPLATES / "sct1b.pdf"))
        writer.pages[0].merge_page(PdfReader(io.BytesIO(buf.getvalue())).pages[0])
        out = io.BytesIO()
        writer.write(out)
        out_pages.append(out.getvalue())
    return out_pages


# --------------------------------------------------------------------------- ReportLab documents

_styles = getSampleStyleSheet()
S_BASE = ParagraphStyle("base", parent=_styles["Normal"], fontName="Helvetica", fontSize=9, leading=11.5)
S_SMALL = ParagraphStyle("small", parent=S_BASE, fontSize=7.5, leading=9)
S_TITLE = ParagraphStyle("title", parent=S_BASE, fontName="Helvetica-Bold", fontSize=10.5, leading=13, alignment=1)
S_RIGHT = ParagraphStyle("right", parent=S_BASE, alignment=2, fontName="Helvetica-Bold")
S_HEAD = ParagraphStyle("head", parent=S_BASE, fontName="Helvetica-Bold", textColor=colors.white)
S_CELL = ParagraphStyle("cell", parent=S_BASE, fontSize=8, leading=10)

SIGNATURE_NOTE = (
    "La presente è resa nella consapevolezza delle sanzioni penali previste nel caso di dichiarazioni mendaci, "
    "richiamate all'articolo 76 del DPR 445/2000. Ai sensi dell'articolo 38 del DPR 445/2000, la presente è "
    "sottoscritta dall'interessato in presenza del dipendente addetto ovvero sottoscritta o inviata, insieme alla "
    "fotocopia non autenticata di un documento di identità, via fax, a mezzo posta ovvero tramite incaricato."
)


def P(text, style=S_BASE):
    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)


def _section(title):
    t = Table([[Paragraph(escape(title), S_HEAD)]], colWidths=[180 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#555555")),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


def _kv_table(pairs, widths=(55 * mm, 125 * mm)):
    t = Table([[P(k, S_SMALL), P(v)] for k, v in pairs], colWidths=widths)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return t


def _rows_table(columns, rows, widths, min_rows=0):
    header = [P(label, S_SMALL) for _, label in columns]
    body = [[P(row.get(col, ""), S_CELL) for col, _ in columns] for row in rows]
    while len(body) < min_rows:
        body.append([P("") for _ in columns])
    t = Table([header] + body, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ROWHEIGHT", (0, 1), (-1, -1), 14)]))
    return t


def _yn(value):
    return "SI [X]   NO [ ]" if value else "SI [ ]   NO [X]"


def _signature_block(place_date, who="Firma"):
    t = Table([[P(f"Luogo e data: {place_date}"), P(f"{who}<br/><br/>_______________________________", S_BASE)]],
              colWidths=[90 * mm, 90 * mm])
    return t


def _doc(build) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm)
    doc.build(build())
    return buf.getvalue()


def _render_sct3(data: dict) -> list[bytes]:
    f = data["fields"]
    spec = FORM_SPECS["SCT3"]

    def build():
        story = [
            P("MODELLO SCT3", S_RIGHT),
            P("SCHEDA INFORMATIVA ANIMALI DI ALLEGATO “A” PER LA RICHIESTA DI CERTIFICATO "
              "AI SENSI DELL’ART. 9.2 DEL REG. (CE) N° 338/97", S_TITLE),
            P("(Utilizzare una scheda per ogni evento di spostamento di esemplari appartenenti alla stessa specie)",
              S_SMALL),
            Spacer(1, 4 * mm),
            P("<b>PARTE RISERVATA AL SOGGETTO/ALLEVAMENTO DI PROVENIENZA</b>"),
            _section("1. DATI SOGGETTO/ALLEVAMENTO DI PROVENIENZA"),
            _kv_table([("Cognome e Nome", f.get("from_name")), ("Telefono", f.get("from_phone")),
                       ("Indirizzo", f.get("from_address")), ("E-mail", f.get("from_email")),
                       ("Nome allevamento (qualora esistente)", f.get("from_farm_name")),
                       ("Indirizzo allevamento", f.get("from_farm_address"))]),
            Spacer(1, 2 * mm),
            _section("2. DATI DEGLI ESEMPLARI DA MOVIMENTARE"),
            _rows_table(spec.row_columns, data.get("rows", []), [55 * mm, 15 * mm, 60 * mm, 50 * mm], min_rows=6),
            Spacer(1, 2 * mm),
            _section("3. PREPARAZIONE, CARICO, TRASPORTO ED ASSISTENZA DURANTE IL TRASPORTO"),
            P("Il sottoscritto, consapevole delle responsabilità assunte con la presente dichiarazione e delle "
              "conseguenze di eventuali inosservanze, si impegna a rispettare le disposizioni di cui all’art. 9.5 del "
              "Reg. (CE) n° 338/97 nonché quanto previsto dal Reg. (CE) n° 1/2005 in merito alla protezione degli "
              "animali durante il trasporto ed alle norme IATA in caso di trasporto per via aerea e dichiara quanto "
              "segue:", S_SMALL),
            _kv_table([
                ("L’idoneità degli animali al viaggio previsto è stata certificata da un medico veterinario",
                 _yn(f.get("vet_certified"))),
                ("Tipologia del mezzo di trasporto", f.get("vehicle")),
                ("Tipologia di contenitori utilizzati", f.get("container")),
                ("Dimensioni del contenitore", f.get("container_size")),
                ("Numero di esemplari per contenitore", f.get("per_container")),
                ("Presenza di setti divisori tra gli animali", _yn(f.get("dividers"))),
                ("Distanza dall’allevamento di provenienza (ore di viaggio)", f.get("travel_time")),
                ("Disponibilità di cibo ed acqua di bevanda durante il viaggio", _yn(f.get("food_water"))),
                ("Presenza e funzionamento sistemi di termoregolazione e ventilazione", _yn(f.get("thermo"))),
                ("Possibilità di proteggere gli animali dalle intemperie", _yn(f.get("weather"))),
            ], widths=(100 * mm, 80 * mm)),
            Spacer(1, 2 * mm),
            P("Note: 1) SPECIE: nome scientifico; 2) SESSO: M = maschio, F = femmina, I = indeterminato; "
              "3) MARCATURA: microchip (indicare anche la casa produttrice e la data di applicazione), anello "
              "inamovibile (uccelli), foto (allegare), altro; 4) TIPO DOCUMENTO: tipologia ed estremi della "
              "documentazione CITES che accompagna l’esemplare, allegandone copia.", S_SMALL),
            Spacer(1, 4 * mm),
            _signature_block(f.get("place_date"), "Firma (soggetto di provenienza)"),
            PageBreak(),
            P("MODELLO SCT3", S_RIGHT),
            P("SCHEDA INFORMATIVA ANIMALI DI ALLEGATO “A” PER LA RICHIESTA DI CERTIFICATO "
              "AI SENSI DELL’ART. 9.2 DEL REG. (CE) N° 338/97", S_TITLE),
            Spacer(1, 4 * mm),
            P("<b>PARTE RISERVATA AL SOGGETTO/ALLEVAMENTO DI DESTINAZIONE</b>"),
            _section("1. DATI SOGGETTO/ALLEVAMENTO DI DESTINAZIONE"),
            _kv_table([("Cognome e nome", f.get("to_name")), ("Telefono", f.get("to_phone")),
                       ("Indirizzo", f.get("to_address")), ("Nome allevamento (qualora esistente)", f.get("to_farm_name")),
                       ("Indirizzo allevamento", f.get("to_farm_address"))]),
            Spacer(1, 2 * mm),
            _section("2. TIPOLOGIA DELL’ALLEVAMENTO"),
            _kv_table([("Tipologia", f.get("to_breeding_type"))]),
            Spacer(1, 2 * mm),
            _section("3. TIPOLOGIE DELLE STRUTTURE RICETTIVE"),
            _kv_table([("Strutture", f.get("to_structures")), ("Dimensioni", f.get("to_dimensions")),
                       ("Tipo di lettiera", f.get("to_litter")), ("Tipo di barriera", f.get("to_barrier"))]),
            Spacer(1, 2 * mm),
            _section("4. MODALITA’ DELLA GESTIONE DELL’ALLEVAMENTO"),
            _kv_table([("Alimentazione", f.get("to_feeding")), ("Igiene", f.get("to_hygiene")),
                       ("Assistenza veterinaria", f.get("to_vet"))]),
            Spacer(1, 2 * mm),
            _section("5. SPECIE ALLEVATE"),
            _kv_table([("Specie", f.get("to_species"))]),
            Spacer(1, 6 * mm),
            _signature_block(f.get("place_date"), "Firma (soggetto di destinazione)"),
        ]
        return story

    return [_doc(build)]


def _render_sale_b(data: dict) -> list[bytes]:
    f = data["fields"]
    spec = FORM_SPECS["CESSB"]

    def build():
        return [
            P("DICHIARAZIONE DI CESSIONE AI FINI CITES", S_TITLE),
            P("Esemplari di specie incluse nell’Allegato B del Reg. (CE) 338/97", S_TITLE),
            Spacer(1, 5 * mm),
            _kv_table([("Cedente", f.get("seller")), ("Cessionario", f.get("buyer")),
                       ("Fattura / ricevuta n.", f.get("invoice"))]),
            Spacer(1, 4 * mm),
            P("Il cedente dichiara che gli esemplari sotto elencati sono stati legalmente acquisiti/riprodotti "
              "e vengono ceduti al cessionario sopra indicato:"),
            Spacer(1, 2 * mm),
            _rows_table(spec.row_columns, data.get("rows", []),
                        [38 * mm, 32 * mm, 10 * mm, 10 * mm, 13 * mm, 37 * mm, 40 * mm], min_rows=4),
            Spacer(1, 6 * mm),
            _signature_block(f.get("place_date"), "Firma del cedente"),
            Spacer(1, 6 * mm),
            _signature_block("", "Firma del cessionario per ricevuta"),
            Spacer(1, 6 * mm),
            P(SIGNATURE_NOTE, S_SMALL),
        ]

    return [_doc(build)]


def _render_letter(data: dict, spec_key: str) -> list[bytes]:
    f = data["fields"]
    spec = FORM_SPECS[spec_key]

    def build():
        story = [
            Table([[P(""), P("Spett.le<br/>" + escape(f.get("office", "")).replace("\n", "<br/>"))]],
                  colWidths=[95 * mm, 85 * mm]),
            Spacer(1, 10 * mm),
            P(f"<b>OGGETTO:</b> {escape(f.get('subject', ''))}"),
            Spacer(1, 6 * mm),
            P(f"Il/la sottoscritto/a {f.get('declarant', '')},"),
            Spacer(1, 2 * mm),
            P(f.get("body", "")),
            Spacer(1, 4 * mm),
        ]
        if data.get("rows"):
            story.append(_rows_table(spec.row_columns, data["rows"], [60 * mm, 15 * mm, 50 * mm, 55 * mm]))
        story += [Spacer(1, 4 * mm), P("Si allega copia del documento di identità."), Spacer(1, 8 * mm),
                  KeepTogether([_signature_block(f.get("place_date"))]), Spacer(1, 8 * mm), P(SIGNATURE_NOTE, S_SMALL)]
        return story

    return [_doc(build)]


# --------------------------------------------------------------------------- entry point

def render_pdf(kind: str, data: dict, flatten: bool | None = None) -> bytes:
    """Render a form. AcroForms stay editable when a single page, flattened when split on more copies."""
    if kind in MAPPINGS:
        n_pages = len(_chunks(data.get("rows"), FORM_SPECS[kind].rows_per_page))
        parts = _fill_acroform(kind, data, flatten=flatten if flatten is not None else n_pages > 1)
    elif kind == "SCT1B":
        parts = _render_sct1b(data)
    elif kind == "SCT3":
        parts = _render_sct3(data)
    elif kind == "CESSB":
        parts = _render_sale_b(data)
    elif kind in ("LOSS", "SITE", "MARK"):
        parts = _render_letter(data, kind)
    else:
        raise ValueError(f"Tipo modulo sconosciuto: {kind}")
    return _merge(parts)


def render_declaration(declaration) -> bytes:
    from .formdata import get_form_data

    return render_pdf(declaration.kind, get_form_data(declaration))
