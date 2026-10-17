"""Classify archive documents and extract structured data for review.

Heuristics are tuned on real Carabinieri CITES paperwork: filled SCT1/A, SCT1/B, SCT3, SCT5
forms, office reply letters ("DC_1234 (10.100-1) DN n. 9 Testudo hermanni ...pdf"),
movement certificates (IT/CE/2024/XX/00001), payment receipts and ID copies.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from apps.pdfforms.render import MAPPINGS

KINDS = {
    "SCT1A": "Denuncia di nascita All. A (SCT1/A)",
    "SCT1B": "Denuncia di nascita All. B (SCT1/B)",
    "SCT5": "Comunicazione decesso (SCT5)",
    "SCT3": "Scheda spostamento/cessione (SCT3)",
    "REPLY": "Risposta / protocollo ufficio CITES",
    "CERT": "Certificato CITES (spostamento / art. 10)",
    "PAYMENT": "Ricevuta pagamento",
    "ID": "Documento d'identità",
    "SHEET": "Foglio di calcolo",
    "OTHER": "Altro / non riconosciuto",
}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
     "novembre", "dicembre"])}

RE_DATE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b")
RE_LONG_DATE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\b", re.I)
RE_CERT = re.compile(r"\bIT\s*/\s*CE\s*/\s*\d{4}\s*/\s*[A-Z]{2}\s*/\s*\d+", re.I)
RE_PROT = re.compile(r"\bProt(?:ocollo)?\.?\s*(?:n\.?\s*)?([0-9]+(?:[./-][0-9]+)*(?:-\d+)?)", re.I)
RE_QTY = re.compile(r"\bn\.?\s*(\d{1,3})\b", re.I)
RE_QTY_ESEMPLARI = re.compile(r"\b(?:n\.?\s*)?(\d{1,3})\s+esemplar", re.I)
RE_MICROCHIP = re.compile(r"\b\d{15}\b")
RE_FILENAME_DC = re.compile(r"DC_([\d.]+(?:-\d+)?)\s*\(([^)]+)\)")
RE_PLACE_DATE = re.compile(r"([A-ZÀ-Ù][a-zà-ù]+(?:\s[A-ZÀ-Ù]?[a-zà-ù]+)?),?\s+(\d{1,2}/\d{1,2}/\d{4})")


@dataclass
class Parsed:
    kind: str = "OTHER"
    confidence: float = 0.0
    data: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def as_dict(self):
        return {"kind": self.kind, "confidence": round(self.confidence, 2), "data": self.data, "rows": self.rows,
                "notes": self.notes}


# --------------------------------------------------------------------------- small parsers

def parse_date(text: str) -> date | None:
    if not text:
        return None
    m = RE_DATE.search(text)
    if m:
        dd, mm, yy = map(int, m.groups())
        try:
            return date(yy, mm, dd)
        except ValueError:
            pass
    m = RE_LONG_DATE.search(text)
    if m:
        try:
            return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            pass
    return None


def all_dates(text: str) -> list[date]:
    out = []
    for m in RE_DATE.finditer(text or ""):
        dd, mm, yy = map(int, m.groups())
        try:
            out.append(date(yy, mm, dd))
        except ValueError:
            continue
    return out


def normalize(text: str) -> str:
    text = re.sub(r"(\d)\s*/\s+(\d)", r"\1/\2", text or "")
    return re.sub(r"[ \t]+", " ", text)


def find_species(text: str, known: list[str], abbreviations: bool = False) -> str:
    low = re.sub(r"\s+", " ", (text or "").lower())
    for name in sorted(known, key=len, reverse=True):
        if name.lower() in low:
            return name
    if abbreviations:
        for name in known:
            parts = name.split()
            if len(parts) < 2:
                continue
            g, s = parts[0], parts[1]
            pattern = rf"(?<![a-z])(?:{g[0]}\.?\s?{s[0]}\.?|{g[:4]}\.?\s+{s[0]})(?![a-z])"
            if re.search(pattern, text or "", re.I):
                return name
    m = re.search(r"\b(Testudo|Python|Boa|Psittacus|Ara|Amazona|Geochelone|Centrochelys|Chelonoidis)\s+([a-z]{4,})",
                  text or "", re.I)
    return f"{m.group(1).capitalize()} {m.group(2).lower()}" if m else ""


def parse_quantity(text: str) -> int | None:
    m = RE_QTY_ESEMPLARI.search(text or "") or RE_QTY.search(text or "")
    return int(m.group(1)) if m else None


def split_lot_label(label: str, known: list[str]) -> tuple[int, str]:
    """'n7 - TESTUDO HERMANNI' / 'Testudo Hermanni n. 1' / 'n. 9 - Testudo hermanni' → (qty, species)."""
    qty = parse_quantity(label) or 1
    return qty, find_species(label, known)


def _iso(d: date | None) -> str:
    return d.isoformat() if d else ""


# --------------------------------------------------------------------------- classification

def classify(filename: str, text: str, form_fields: dict) -> tuple[str, float]:
    name = filename.lower()
    up = (text or "").upper()
    if "Campo di testo 2_38" in form_fields or "Campo di testo 2_5" in form_fields:
        return "SCT1A", 0.95
    if "Campo di testo 7_11" in form_fields:
        return "SCT5", 0.95
    if "SCT1/A" in up:
        return "SCT1A", 0.9
    if "SCT1/B" in up:
        return "SCT1B", 0.9
    if "SCT5" in up or "AVVENUTO DECESSO" in up:
        return "SCT5", 0.9
    if "SCT3" in up or "SCHEDA INFORMATIVA ANIMALI" in up:
        return "SCT3", 0.85
    if RE_CERT.search(text or "") and "CERTIFICATO" in up and "PROT." not in up:
        return "CERT", 0.7
    if ("NUCLEO CITES" in up or "SERVIZIO CITES" in up or "CARABINIERI" in up) and "PROT" in up:
        return "REPLY", 0.8
    if name.startswith("dc_") or RE_FILENAME_DC.search(filename):
        return "REPLY", 0.7
    if any(k in name for k in ("nuove nate", "nuovi nati", "microchip", "marcatura")):
        return "REPLY", 0.5
    if any(k in name for k in ("pagamento", "bonifico", "prelievo", "ricevuta")):
        return "PAYMENT", 0.7
    if any(k in name for k in ("identit", "carta id", "ci ", "patente", "passaporto")):
        return "ID", 0.6
    if "nascit" in name:
        return "SCT1A", 0.4
    if "decesso" in name:
        return "SCT5", 0.4
    if "cessione" in name:
        return "SCT3", 0.4
    if name.endswith(".xlsx"):
        return "SHEET", 0.9
    return "OTHER", 0.1


# --------------------------------------------------------------------------- per-kind extraction

def _reverse(kind: str, form_fields: dict) -> tuple[dict, list]:
    mapping = MAPPINGS[kind]
    fields = {key: form_fields.get(name, "") for key, name in mapping["fields"].items()}
    rows = []
    for row_map in mapping["rows"]:
        row = {col: form_fields.get(name, "") for col, name in row_map.items()}
        if any(v.strip() for v in row.values()):
            rows.append(row)
    return fields, rows


def _text_birth_rows(text: str, known: list[str]) -> list[dict]:
    rows = []
    for line in (text or "").splitlines():
        m = re.match(r"\s*(\d{1,2})\s+(.+)", line)
        if not m:
            continue
        rest = m.group(2)
        bdate = parse_date(rest)
        species = find_species(rest, known)
        if not (species and bdate):
            continue
        rows.append({"scientific_name": rest.split(RE_DATE.search(rest).group(0))[0].strip(),
                     "birth_date": bdate.strftime("%d/%m/%Y")})
    return rows


def parse_birth(p: Parsed, text, form_fields, known):
    if p.kind == "SCT1A" and form_fields:
        fields, rows = _reverse("SCT1A", form_fields)
    else:
        fields, rows = {}, _text_birth_rows(text, known)
        m = re.search(r"(?:Luogo e data:?)?\s*([A-Z][a-zà-ù]+)\s+(\d{1,2}/\d{1,2}/\d{4})\s*\n", text or "")
        if m:
            fields["place_date"] = f"{m.group(1)} {m.group(2)}"
        if "place_date" not in fields and "Luogo e data" in (text or ""):
            before = all_dates((text or "").split("Luogo e data")[0][-200:])
            if before:
                fields["place_date"] = before[-1].strftime("%d/%m/%Y")
        prot = re.search(r"PROT\.?\s*\d+\s+DEL\s+\d{4}", text or "", re.I)
        if prot:
            fields["other"] = prot.group(0)
    lots = []
    for row in rows:
        qty, species = split_lot_label(row.get("scientific_name", ""), known)
        lots.append({"species": species, "quantity": qty, "birth_date": _iso(parse_date(row.get("birth_date", ""))),
                     "marking_type": row.get("marking_type", ""), "marking_code": row.get("marking_code", "")})
    p.rows = lots
    first = lots[0] if lots else {}
    p.data.update({
        "species": first.get("species", ""),
        "quantity": sum(r["quantity"] for r in lots) if lots else None,
        "event_date": first.get("birth_date", ""),
        "signed_on": _iso(parse_date(fields.get("place_date", ""))),
        "breeding_group": fields.get("other", ""),
    })
    if not lots:
        p.notes.append("Nessuna riga esemplari riconosciuta: completare a mano.")
        p.confidence = min(p.confidence, 0.4)


def parse_death(p: Parsed, text, form_fields, known):
    if form_fields:
        fields, rows = _reverse("SCT5", form_fields)
    else:
        fields, rows = {}, []
        for line in (text or "").splitlines():
            species = find_species(line, known)
            if species and ("n." in line.lower() or "/" in line):
                rows.append({"scientific_name": line.strip(), "document": ""})
        m = RE_PLACE_DATE.search((text or "").split("Luogo e data")[-1]) if "Luogo e data" in (text or "") else None
        if m:
            fields["place_date"] = f"{m.group(1)} {m.group(2)}"
    lots = []
    for row in rows:
        qty, species = split_lot_label(row.get("scientific_name", ""), known)
        lots.append({"species": species, "quantity": qty, "marking": row.get("marking", ""),
                     "document": row.get("document", "")})
    p.rows = lots
    signed = parse_date(fields.get("place_date", ""))
    p.data.update({
        "species": lots[0]["species"] if lots else find_species(text, known),
        "quantity": sum(r["quantity"] for r in lots) if lots else parse_quantity(text),
        "event_date": _iso(signed),
        "signed_on": _iso(signed),
        "document": lots[0]["document"] if lots else "",
    })
    p.notes.append("La data del decesso non è sul modulo: verificare (proposta = data firma).")


def parse_transfer(p: Parsed, text, form_fields, known):
    chips = RE_MICROCHIP.findall(text or "")
    p.data.update({
        "species": find_species(text, known),
        "quantity": max(len(chips), 1) if chips else parse_quantity(text) or 1,
        "event_date": _iso(all_dates(text)[-1] if all_dates(text) else None),
        "microchips": chips,
    })
    m = re.search(r"Cognome e [Nn]ome:?\s*(.+?)\s+Telefono", text or "")
    if m:
        p.data["from_name"] = m.group(1).strip()


def parse_reply(p: Parsed, text, filename, known):
    """Office letters and filename conventions like 'DC_1234 (10.100-1) DN n. 9 Testudo hermanni'."""
    low = (filename + " " + (text or "")).lower()
    fm = RE_FILENAME_DC.search(filename)
    number = ""
    if fm:
        number = f"{fm.group(1)} ({fm.group(2)})"
    pm = RE_PROT.search(text or "")
    if pm and not number:
        number = pm.group(1)
    cert = RE_CERT.search(text or "") or RE_CERT.search(filename.replace(" ", ""))
    if " dn " in f" {low} " or any(k in low for k in ("nascit", " nate ", " nati ")):
        doc_type, related = "dn", "SCT1A"
    elif "decesso" in low:
        doc_type, related = "dd", "SCT5"
    elif "spost" in low or cert:
        doc_type, related = "art9", "SCT3"
    elif "microchip" in low or "marcatura" in low:
        doc_type, related = "other", "MARK"
    else:
        doc_type, related = "other", ""
    dates = all_dates(text)
    letter_date = parse_date(text) if text else None
    long_date = RE_LONG_DATE.search(text or "")
    if long_date:
        letter_date = parse_date(long_date.group(0))
    p.data.update({
        "doc_type": doc_type,
        "related_kind": related,
        "number": number,
        "certificate_number": re.sub(r"\s+", "", cert.group(0)).upper() if cert else "",
        "issued_on": _iso(letter_date or (dates[0] if dates else None)),
        "species": find_species(filename + " " + (text or ""), known)
        or find_species(filename.rsplit(".", 1)[0], known, abbreviations=True),
        "quantity": parse_quantity(filename) or _bare_quantity(filename) or parse_quantity(text) or None,
        "microchips": RE_MICROCHIP.findall(text or ""),
    })
    if not text:
        p.notes.append("Dati ricavati dal nome file (documento scansionato senza OCR).")


def _bare_quantity(filename: str) -> int | None:
    """'Rossi 7 Th.pdf', 'Spost 4 test h' → 7, 4."""
    m = re.search(r"(?:^|\s)(\d{1,2})\s+(?:[A-Z][a-z]?\.?\s?[a-z]?\.?|test)", filename.rsplit(".", 1)[0])
    return int(m.group(1)) if m else None


def parse_payment(p: Parsed, text, filename):
    amount = None
    m = re.search(r"(?:€|EUR|importo)\s*:?\s*(\d{1,4}[.,]\d{2})", text or "", re.I)
    if m:
        amount = m.group(1).replace(",", ".")
    dates = all_dates(text)
    p.data.update({"amount": amount, "paid_on": _iso(dates[0] if dates else None),
                   "reference": (re.search(r"(?:CRO|TRN|IUV)[:\s]*([A-Z0-9]{8,})", text or "", re.I) or [None, ""])[1]})


def parse(filename: str, text: str, form_fields: dict, known_species: list[str]) -> Parsed:
    text = normalize(text)
    kind, conf = classify(filename, text, form_fields)
    p = Parsed(kind=kind, confidence=conf)
    if kind in ("SCT1A", "SCT1B"):
        parse_birth(p, text, form_fields, known_species)
    elif kind == "SCT5":
        parse_death(p, text, form_fields, known_species)
    elif kind == "SCT3":
        parse_transfer(p, text, form_fields, known_species)
    elif kind in ("REPLY", "CERT"):
        parse_reply(p, text, filename, known_species)
    elif kind == "PAYMENT":
        parse_payment(p, text, filename)
    return p
