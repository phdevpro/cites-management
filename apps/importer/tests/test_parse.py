import io
from datetime import date
from pathlib import Path

import pytest
from django.core.files.base import ContentFile

from apps.importer.extract import extract
from apps.importer.parse import classify, find_species, parse, parse_date
from apps.pdfforms.render import render_pdf

KNOWN = ["Testudo hermanni", "Testudo graeca", "Python regius"]


def test_dates():
    assert parse_date("Udine, 12/10/2025") == date(2025, 10, 12)
    assert parse_date("Trieste, 20 settembre 2024") == date(2024, 9, 20)


def test_species_abbreviations():
    assert find_species("TESTUDO HERMANNI n 12", KNOWN) == "Testudo hermanni"
    assert find_species("Rossi decesso n.1 T.h.", KNOWN, abbreviations=True) == "Testudo hermanni"
    assert find_species("Spost 4 test h Rossi", KNOWN, abbreviations=True) == "Testudo hermanni"


def test_reply_filename():
    p = parse("DC_1234 (10.100-1) DN n. 9 Testudo hermanni ROSSI M..pdf", "", {}, KNOWN)
    assert p.kind == "REPLY"
    assert p.data["doc_type"] == "dn"
    assert p.data["number"] == "1234 (10.100-1)"
    assert p.data["quantity"] == 9 and p.data["species"] == "Testudo hermanni"
    p = parse("DC_11.22 (3333) ROSSI decesso n.1 Testudo hermanni.pdf", "", {}, KNOWN)
    assert p.data["doc_type"] == "dd" and p.data["quantity"] == 1
    p = parse("DC_44.55-3 (4444) - Spost 4 test h Rossi Bianchi.pdf", "", {}, KNOWN)
    assert p.data["doc_type"] == "art9" and p.data["quantity"] == 4 and p.data["species"] == "Testudo hermanni"


def test_certificate_in_text():
    text = "Nucleo CITES Trieste\nProt. 44/55-3\nTrieste, 20 settembre 2024\nè stato emesso il certificato n. IT/CE/2024/XX/00001"
    p = parse("lettera.pdf", text, {}, KNOWN)
    assert p.kind == "REPLY"
    assert p.data["certificate_number"] == "IT/CE/2024/XX/00001"
    assert p.data["issued_on"] == "2024-09-20"


def test_filled_sct1a_roundtrip(tmp_path):
    pdf = render_pdf("SCT1A", {"fields": {"office": "Trieste", "other": "PROT 123 DEL 1999",
                                          "place_date": "Udine, 12/10/2025"},
                               "rows": [{"scientific_name": "n7 - TESTUDO HERMANNI", "common_name": "N/A",
                                         "birth_date": "04/10/2025", "marking_type": "N/A", "marking_code": "N/A"}]},
                     flatten=False)
    path = tmp_path / "denuncia.pdf"
    path.write_bytes(pdf)
    ex = extract(path)
    assert ex.method == "acroform"
    p = parse(path.name, ex.text, ex.form_fields, KNOWN)
    assert p.kind == "SCT1A"
    assert p.data["species"] == "Testudo hermanni"
    assert p.data["quantity"] == 7
    assert p.data["event_date"] == "2025-10-04"
    assert p.data["signed_on"] == "2025-10-12"
    assert p.data["breeding_group"] == "PROT 123 DEL 1999"


def test_filled_sct5_roundtrip(tmp_path):
    pdf = render_pdf("SCT5", {"fields": {"name": "Mario Rossi", "place_date": "Udine 20/07/2025"},
                              "rows": [{"scientific_name": "Testudo Hermanni n. 1", "document": "1234 - 31/10/2024"}]},
                     flatten=False)
    path = tmp_path / "decesso.pdf"
    path.write_bytes(pdf)
    ex = extract(path)
    p = parse(path.name, ex.text, ex.form_fields, KNOWN)
    assert p.kind == "SCT5"
    assert p.data["quantity"] == 1 and p.data["event_date"] == "2025-07-20"
    assert p.data["document"] == "1234 - 31/10/2024"


@pytest.mark.django_db
def test_import_apply_birth_then_reply(keeper, user, hermanni, tmp_path, settings):
    from apps.importer import services
    from apps.importer.forms import ReviewForm
    from apps.importer.models import ImportBatch

    settings.MEDIA_ROOT = tmp_path
    batch = ImportBatch.objects.create(keeper=keeper)
    pdf = render_pdf("SCT1A", {"fields": {"place_date": "Udine 26/10/2024"},
                               "rows": [{"scientific_name": "n9 - TESTUDO HERMANNI", "birth_date": "18/10/2024"}]},
                     flatten=False)
    f, msg = services.add_file(batch, ContentFile(pdf, name="denuncia_nascita_2024.pdf"), "denuncia_nascita_2024.pdf",
                               "2024/denuncia_nascita_2024.pdf")
    assert f and f.detected_kind == "SCT1A" and f.year_hint == 2024
    dup, msg = services.add_file(batch, ContentFile(pdf, name="copy.pdf"), "copy.pdf")
    assert dup is None and "già importato" in msg

    from apps.importer.views import _initial
    form = ReviewForm(data={**{k: v for k, v in _initial(f).items() if v is not None},
                            "event_date": "2024-10-18", "signed_on": "2024-10-26"}, keeper=keeper)
    assert form.is_valid(), form.errors
    services.apply(f, form.cleaned_data, user)
    f.refresh_from_db()
    decl = f.declaration
    assert decl.imported and decl.status == "sent" and decl.deadline is None
    assert decl.items.get().specimen.quantity == 9
    assert decl.attachments.filter(kind="original").exists()

    reply, _ = services.add_file(batch, ContentFile(b"%PDF-1.4 fake", name="r.pdf"),
                                 "DC_1234 (10.100-1) DN n. 9 Testudo hermanni.pdf")
    form = ReviewForm(data={"action": "document", "doc_type": "dn", "number": "1234 (10.100-1)",
                            "issued_on": "2024-10-31", "link_declaration": decl.pk}, keeper=keeper)
    assert form.is_valid(), form.errors
    services.apply(reply, form.cleaned_data, user)
    decl.refresh_from_db()
    assert decl.status == "protocolled" and decl.protocol_number == "1234 (10.100-1)"
    sp = decl.items.get().specimen
    assert sp.current_document.number == "1234 (10.100-1)"


@pytest.mark.django_db
def test_sheet_import(keeper, user, hermanni):
    from apps.importer.services import import_specimen_sheet, sheet_template

    count, errors = import_specimen_sheet(keeper, user, io.BytesIO(sheet_template()))
    assert count == 1 and not errors
    from apps.registry.models import Specimen
    sp = Specimen.objects.get()
    assert sp.sex == "F" and sp.markings.get().code == "380260000000000"
    assert sp.current_document.number == "PROT 123 DEL 1999"
