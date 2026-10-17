"""Build the editable data ("dati modulo") of each official form from the database.

Data shape (stored in Declaration.data["form"]):
    {"fields": {key: str | bool}, "rows": [{col: str}, ...]}

FORM_SPECS describes, per declaration kind, the fields and row columns shown in the editor
and consumed by the renderers in `render.py`.
"""

from dataclasses import dataclass, field


def d(value):
    return value.strftime("%d/%m/%Y") if value else ""


@dataclass
class FieldSpec:
    key: str
    label: str
    kind: str = "text"  # text | textarea | bool
    help: str = ""


@dataclass
class FormSpec:
    title: str
    fields: list[FieldSpec]
    row_columns: list[tuple[str, str]] = field(default_factory=list)
    rows_per_page: int = 6


_BIRTH_COMMON = [
    FieldSpec("office", "Servizio/Nucleo CITES di"),
    FieldSpec("declarant", "Generalità denunciante (nome, cognome, luogo e data nascita, doc. identità)", "textarea"),
    FieldSpec("domicile", "Domicilio e recapito telefonico", "textarea"),
    FieldSpec("site_address", "Indirizzo sito di detenzione", "textarea"),
    FieldSpec("site_phone", "Telefono/fax sito"),
]
_BIRTH_ROWS = [
    ("scientific_name", "Nome scientifico"),
    ("common_name", "Nome comune"),
    ("birth_date", "Data nascita"),
    ("marking_type", "Tipo marcatura"),
    ("marking_code", "Estremi marcatura"),
]

FORM_SPECS: dict[str, FormSpec] = {
    "SCT1A": FormSpec(
        "Modello SCT1/A – Denuncia di nascita (All. A)",
        _BIRTH_COMMON + [
            FieldSpec("father_import", "Licenza importazione – maschio"),
            FieldSpec("mother_import", "Licenza importazione – femmina"),
            FieldSpec("father_eucert", "Certificato comunitario – maschio"),
            FieldSpec("mother_eucert", "Certificato comunitario – femmina"),
            FieldSpec("father_marking", "Marcatura riproduttori – maschio"),
            FieldSpec("mother_marking", "Marcatura riproduttori – femmina"),
            FieldSpec("other", "Altro (gruppo riproduttore, protocolli)", "textarea"),
            FieldSpec("place_date", "Luogo e data"),
        ],
        _BIRTH_ROWS, 6,
    ),
    "SCT1B": FormSpec(
        "Modello SCT1/B – Denuncia di nascita (All. B)",
        _BIRTH_COMMON + [
            FieldSpec("art54_yes", "Dichiarazione conformità art. 54 presentata", "bool"),
            FieldSpec("art54_date", "Art. 54 – data presentazione"),
            FieldSpec("art54_protocol", "Art. 54 – estremi protocollo"),
            FieldSpec("parents_import", "Riproduttori – licenza importazione"),
            FieldSpec("parents_eucert", "Riproduttori – certificato comunitario"),
            FieldSpec("parents_marking", "Riproduttori – marcatura"),
            FieldSpec("other", "Riproduttori – altro"),
            FieldSpec("place_date", "Luogo e data"),
        ],
        _BIRTH_ROWS, 6,
    ),
    "SCT5": FormSpec(
        "Modello SCT5 – Comunicazione di decesso (All. A)",
        [
            FieldSpec("office_city", "Servizio CITES Territoriale Carabinieri di"),
            FieldSpec("name", "Il/la sottoscritto/a"),
            FieldSpec("birth_place", "Nato a"),
            FieldSpec("birth_province", "Prov. nascita"),
            FieldSpec("birth_date", "Data di nascita"),
            FieldSpec("city", "Residente a"),
            FieldSpec("province", "Prov. residenza"),
            FieldSpec("phone", "Telefono"),
            FieldSpec("street", "Via"),
            FieldSpec("id_doc", "Documento identità n."),
            FieldSpec("place_date", "Luogo e data"),
        ],
        [("scientific_name", "Nome scientifico"), ("common_name", "Nome comune"),
         ("marking", "Marcatura"), ("document", "Certificato o altro documento CITES")],
        2,
    ),
    "SCT3": FormSpec(
        "Modello SCT3 – Scheda informativa spostamento All. A (art. 9.2 Reg. CE 338/97)",
        [
            FieldSpec("from_name", "Provenienza – cognome e nome"),
            FieldSpec("from_phone", "Provenienza – telefono"),
            FieldSpec("from_address", "Provenienza – indirizzo"),
            FieldSpec("from_email", "Provenienza – e-mail"),
            FieldSpec("from_farm_name", "Provenienza – nome allevamento"),
            FieldSpec("from_farm_address", "Provenienza – indirizzo allevamento"),
            FieldSpec("vet_certified", "Idoneità al viaggio certificata da veterinario", "bool"),
            FieldSpec("vehicle", "Mezzo di trasporto", help="Automezzo / Nave / Aereo / Altro"),
            FieldSpec("container", "Contenitore", help="Scatola di cartone / Gabbia metallica / Plastica / Legno"),
            FieldSpec("container_size", "Dimensioni contenitore"),
            FieldSpec("per_container", "Esemplari per contenitore"),
            FieldSpec("dividers", "Setti divisori tra animali", "bool"),
            FieldSpec("travel_time", "Distanza (ore:minuti di viaggio)"),
            FieldSpec("food_water", "Cibo e acqua durante il viaggio", "bool"),
            FieldSpec("thermo", "Sistemi termoregolazione/ventilazione", "bool"),
            FieldSpec("weather", "Protezione dalle intemperie", "bool"),
            FieldSpec("place_date", "Luogo e data"),
            FieldSpec("to_name", "Destinazione – cognome e nome"),
            FieldSpec("to_phone", "Destinazione – telefono"),
            FieldSpec("to_address", "Destinazione – indirizzo"),
            FieldSpec("to_farm_name", "Destinazione – nome allevamento"),
            FieldSpec("to_farm_address", "Destinazione – indirizzo allevamento"),
            FieldSpec("to_breeding_type", "Tipologia allevamento destinazione",
                      help="Commerciale / Amatoriale / Zoo / Centro recupero / Altro"),
            FieldSpec("to_structures", "Strutture ricettive", help="Voliera / Gabbia / Recinto / Terrario / Nursery"),
            FieldSpec("to_dimensions", "Dimensioni strutture"),
            FieldSpec("to_litter", "Tipo di lettiera"),
            FieldSpec("to_barrier", "Tipo di barriera"),
            FieldSpec("to_feeding", "Alimentazione"),
            FieldSpec("to_hygiene", "Igiene"),
            FieldSpec("to_vet", "Assistenza veterinaria"),
            FieldSpec("to_species", "Specie allevate"),
        ],
        [("scientific_name", "Specie"), ("sex", "Sesso"), ("marking", "Tipo ed estremi marcatura"),
         ("document", "Tipo documento")],
        10,
    ),
    "CESSB": FormSpec(
        "Dichiarazione di cessione ai fini CITES (All. B)",
        [
            FieldSpec("seller", "Cedente", "textarea"),
            FieldSpec("buyer", "Cessionario", "textarea"),
            FieldSpec("invoice", "Fattura/ricevuta n."),
            FieldSpec("place_date", "Luogo e data"),
        ],
        [("scientific_name", "Nome scientifico"), ("common_name", "Nome comune"), ("quantity", "Q.tà"),
         ("annex", "All."), ("source", "Origine"), ("marking", "Marcatura"), ("document", "Documento CITES")],
        15,
    ),
}

_LETTER = FormSpec(
    "Comunicazione al Servizio CITES",
    [
        FieldSpec("office", "Destinatario"),
        FieldSpec("subject", "Oggetto"),
        FieldSpec("declarant", "Il/la sottoscritto/a (generalità)", "textarea"),
        FieldSpec("body", "Testo", "textarea"),
        FieldSpec("place_date", "Luogo e data"),
    ],
    [("scientific_name", "Nome scientifico"), ("quantity", "Q.tà"), ("marking", "Marcatura"),
     ("document", "Documento CITES")],
    15,
)
for _k in ("LOSS", "SITE", "MARK"):
    FORM_SPECS[_k] = _LETTER


# --------------------------------------------------------------------------- builders

def _declarant_line(k):
    birth = f"{k.birth_place} ({k.birth_province}) {d(k.birth_date)}".strip() if k.birth_place else d(k.birth_date)
    return ", ".join(p for p in [k.full_name, birth, k.id_doc_label] if p)


def _phone(p):
    return p or ""


def _place_date(decl):
    return f"{decl.place} {d(decl.signed_on)}".strip()


def _office_name(decl):
    return decl.office.city if decl.office else ""


def _lot_name(item):
    sp = item.specimen
    name = sp.species.scientific_name
    return f"n. {item.quantity} - {name}" if item.quantity > 1 else name


def _marking_type(sp):
    return sp.marking_types_label or "N/A"


def _marking_code(sp):
    return sp.marking_codes_label or "N/A"


def _doc_label(item):
    if item.document:
        return item.document.form_label
    doc = item.specimen.current_document
    return doc.form_label if doc else ""


def _parent_docs(parent, doc_types):
    if not parent:
        return ""
    docs = parent.cites_documents.filter(doc_type__in=doc_types)
    return "; ".join(f"{x.number} del {d(x.issued_on)} ({x.issuer})".replace(" ()", "") for x in docs)


def _birth(decl):
    k = decl.keeper
    site = k.default_site
    items = list(decl.items.select_related("specimen__species", "specimen__father", "specimen__mother"))
    first = items[0].specimen if items else None
    father = first.father if first else None
    mother = first.mother if first else None
    rows = [
        {
            "scientific_name": _lot_name(i),
            "common_name": i.specimen.species.common_name or "N/A",
            "birth_date": d(i.specimen.birth_date),
            "marking_type": _marking_type(i.specimen),
            "marking_code": _marking_code(i.specimen),
        }
        for i in items
    ]
    fields = {
        "office": _office_name(decl),
        "declarant": _declarant_line(k),
        "domicile": f"{k.full_address}",
        "site_address": site.full_address if site else k.full_address,
        "site_phone": (site.phone if site and site.phone else k.phone),
        "place_date": _place_date(decl),
    }
    other = first.breeding_group if first else ""
    if decl.kind == "SCT1A":
        fields.update({
            "father_import": _parent_docs(father, ["import"]),
            "mother_import": _parent_docs(mother, ["import"]),
            "father_eucert": _parent_docs(father, ["art10", "eucert"]),
            "mother_eucert": _parent_docs(mother, ["art10", "eucert"]),
            "father_marking": father.markings_label if father else "",
            "mother_marking": mother.markings_label if mother else "",
            "other": other,
        })
    else:
        fields.update({
            "art54_yes": bool(site and site.art54_submitted_on),
            "art54_date": d(site.art54_submitted_on) if site else "",
            "art54_protocol": site.art54_protocol if site else "",
            "parents_import": "; ".join(filter(None, [_parent_docs(father, ["import"]), _parent_docs(mother, ["import"])])),
            "parents_eucert": "; ".join(filter(None, [_parent_docs(father, ["art10", "eucert"]),
                                                      _parent_docs(mother, ["art10", "eucert"])])),
            "parents_marking": "; ".join(filter(None, [father.markings_label if father else "",
                                                       mother.markings_label if mother else ""])),
            "other": other,
        })
    return {"fields": fields, "rows": rows}


def _death(decl):
    k = decl.keeper
    rows = [
        {
            "scientific_name": f"{i.specimen.species.scientific_name} n. {i.quantity}",
            "common_name": i.specimen.species.common_name,
            "marking": i.specimen.marking_codes_label or "N/P",
            "document": _doc_label(i),
        }
        for i in decl.items.select_related("specimen__species")
    ]
    return {
        "fields": {
            "office_city": _office_name(decl),
            "name": k.full_name,
            "birth_place": k.birth_place,
            "birth_province": k.birth_province,
            "birth_date": d(k.birth_date),
            "city": k.city,
            "province": k.province,
            "phone": k.phone,
            "street": k.address,
            "id_doc": k.id_doc_number,
            "place_date": _place_date(decl),
        },
        "rows": rows,
    }


def _transfer(decl):
    k = decl.keeper
    cp = decl.counterparty
    site = k.default_site
    items = list(decl.items.select_related("specimen__species"))
    rows = [
        {
            "scientific_name": _lot_name(i),
            "sex": i.specimen.sex,
            "marking": i.specimen.markings_label or "N/P",
            "document": _doc_label(i),
        }
        for i in items
    ]
    species = sorted({i.specimen.species.scientific_name for i in items})
    return {
        "fields": {
            "from_name": f"{k.last_name} {k.first_name}",
            "from_phone": k.phone,
            "from_address": k.full_address,
            "from_email": k.email,
            "from_farm_name": site.name if site else "",
            "from_farm_address": site.full_address if site else "",
            "vet_certified": False,
            "vehicle": "Automezzo",
            "container": "Scatola di cartone",
            "container_size": "30x30x30 cm",
            "per_container": "1",
            "dividers": False,
            "travel_time": "0:30",
            "food_water": True,
            "thermo": False,
            "weather": True,
            "place_date": _place_date(decl),
            "to_name": f"{cp.last_name} {cp.first_name}".strip() if cp else "",
            "to_phone": cp.phone if cp else "",
            "to_address": cp.full_address if cp else "",
            "to_farm_name": cp.company_name if cp else "",
            "to_farm_address": "",
            "to_breeding_type": (cp.get_breeding_type_display() if cp and cp.breeding_type else "Amatoriale"),
            "to_structures": "Recinto",
            "to_dimensions": "",
            "to_litter": "",
            "to_barrier": "",
            "to_feeding": "",
            "to_hygiene": "",
            "to_vet": "",
            "to_species": ", ".join(species),
        },
        "rows": rows,
    }


def _sale_b(decl):
    k = decl.keeper
    cp = decl.counterparty
    rows = [
        {
            "scientific_name": i.specimen.species.scientific_name,
            "common_name": i.specimen.species.common_name,
            "quantity": str(i.quantity),
            "annex": i.specimen.species.eu_annex,
            "source": i.specimen.source_code,
            "marking": i.specimen.markings_label,
            "document": _doc_label(i),
        }
        for i in decl.items.select_related("specimen__species")
    ]
    buyer = ""
    if cp:
        buyer = "\n".join(filter(None, [cp.full_name, cp.full_address, f"C.F. {cp.fiscal_code}" if cp.fiscal_code else "",
                                        f"Doc. {cp.id_doc_number}" if cp.id_doc_number else ""]))
    return {
        "fields": {
            "seller": "\n".join(filter(None, [str(k), k.full_address, f"C.F. {k.fiscal_code}" if k.fiscal_code else ""])),
            "buyer": buyer,
            "invoice": "",
            "place_date": _place_date(decl),
        },
        "rows": rows,
    }


_LETTER_TEXT = {
    "LOSS": (
        "Comunicazione di {loss} di esemplari (art. 5, comma 2, L. 150/1992)",
        "comunica che in data {date} si è verificato/a {loss} dei seguenti esemplari detenuti presso {site}."
        "{notes}",
    ),
    "SITE": (
        "Comunicazione di variazione del luogo di detenzione (art. 5, comma 2, L. 150/1992)",
        "comunica che a decorrere dal {date} i seguenti esemplari sono detenuti presso il nuovo sito: {site}.{notes}",
    ),
    "MARK": (
        "Comunicazione di avvenuta marcatura di esemplari (Reg. CE 865/2006)",
        "comunica che in data {date} è stata applicata la marcatura ai seguenti esemplari.{notes}",
    ),
}


def _letter(decl):
    k = decl.keeper
    site = k.default_site
    subject, body = _LETTER_TEXT[decl.kind]
    loss = (decl.data or {}).get("loss_type", "smarrimento").lower()
    fmt = {"loss": loss, "date": d(decl.event_date), "site": site.full_address if site else k.full_address,
           "notes": f"\n{decl.notes}" if decl.notes else ""}
    rows = [
        {
            "scientific_name": i.specimen.species.scientific_name,
            "quantity": str(i.quantity),
            "marking": i.specimen.markings_label,
            "document": _doc_label(i),
        }
        for i in decl.items.select_related("specimen__species")
    ]
    office = decl.office
    return {
        "fields": {
            "office": f"{office.name}\n{office.address}" if office else "",
            "subject": subject.format(**fmt),
            "declarant": _declarant_line(k) + (f", residente in {k.full_address}" if k.full_address else "")
            + (f", tel. {k.phone}" if k.phone else ""),
            "body": body.format(**fmt),
            "place_date": _place_date(decl),
        },
        "rows": rows,
    }


BUILDERS = {"SCT1A": _birth, "SCT1B": _birth, "SCT5": _death, "SCT3": _transfer, "CESSB": _sale_b,
            "LOSS": _letter, "SITE": _letter, "MARK": _letter}


def build_form_data(declaration) -> dict:
    return BUILDERS[declaration.kind](declaration)


def get_form_data(declaration) -> dict:
    """Saved (possibly user-edited) data, else freshly built defaults."""
    saved = (declaration.data or {}).get("form")
    return saved if saved else build_form_data(declaration)

