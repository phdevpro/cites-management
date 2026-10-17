import io
import os
import re
from datetime import date
from pathlib import Path

import pytest
from django.conf import settings
from pypdf import PdfReader

from apps.declarations import services
from apps.pdfforms.formdata import build_form_data
from apps.pdfforms.render import TEMPLATES, render_declaration, render_pdf


def _fields(pdf: bytes) -> dict:
    return {k: v.get("/V") for k, v in (PdfReader(io.BytesIO(pdf)).get_fields() or {}).items() if v.get("/V")}


def _text(pdf: bytes) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)


def _private_needles() -> set[bytes]:
    """Values filled in the keeper's own archive forms (local, git-ignored): none may leak into templates.
    Set CITES_PRIVATE_ARCHIVE to point elsewhere; without an archive only the generic checks run."""
    root = Path(os.environ.get("CITES_PRIVATE_ARCHIVE", settings.BASE_DIR / "CITES Denuncia Tartarughe"))
    needles = set()
    if not root.is_dir():
        return needles
    for pdf in root.rglob("*.pdf"):
        try:
            fields = PdfReader(str(pdf)).get_fields() or {}
        except Exception:
            continue
        for f in fields.values():
            for token in re.split(r"[\s,;()/-]+", str(f.get("/V") or "")):
                if len(token) >= 5 and not token.isdigit() or (token.isdigit() and len(token) >= 7):
                    needles.add(token.lower().encode())
    return needles - {b"testudo", b"hermanni", b"trieste"}


@pytest.mark.parametrize("name", ["sct1a.pdf", "sct1b.pdf"])
def test_templates_contain_no_personal_data(name):
    """Templates were derived from filled copies: make sure nothing personal survived (incl. compressed streams)."""
    raw = (TEMPLATES / name).read_bytes()
    blobs = [raw]
    reader = PdfReader(str(TEMPLATES / name))
    for i in range(1, int(reader.trailer["/Size"])):
        try:
            obj = reader.get_object(i)
        except Exception:
            continue
        if hasattr(obj, "get_data"):
            try:
                blobs.append(obj.get_data())
            except Exception:
                pass
        if hasattr(obj, "get") and obj.get("/Subtype") == "/Image":
            pytest.fail(f"image (e.g. signature) found in {name}")
    joined = b"\n".join(blobs).lower()
    assert b"fillsign" not in joined
    assert b"/author" not in raw.lower()
    leaked = [n for n in _private_needles() if n in joined]
    assert not leaked, f"{len(leaked)} private values found in {name}"
    assert not any((f.get("/V") or "") for f in (reader.get_fields() or {}).values())


@pytest.mark.django_db
def test_sct1a_from_declaration(keeper, user, hermanni):
    res = services.register_birth(keeper=keeper, user=user, species=hermanni, birth_date=date(2024, 10, 18),
                                  rows=[services.NewbornSpec(quantity=9)], breeding_group="PROT 123 DEL 1999")
    data = build_form_data(res.declaration)
    assert data["fields"]["office"] == "Testcity"
    assert data["fields"]["declarant"].startswith("Mario Rossi, Udine (UD) 01/02/1980")
    assert data["rows"][0]["scientific_name"] == "n. 9 - Testudo hermanni"
    fields = _fields(render_declaration(res.declaration))
    assert fields["Campo di testo 2"] == "n. 9 - Testudo hermanni"
    assert fields["Campo di testo 2_3"] == "18/10/2024"
    assert fields["Campo di testo 2_37"] == "PROT 123 DEL 1999"
    assert fields["Campo di testo 4"] == "Testcity"


def test_sct1a_overflow_paginates():
    rows = [{"scientific_name": f"Testudo hermanni {i}", "birth_date": "01/01/2025"} for i in range(8)]
    pdf = render_pdf("SCT1A", {"fields": {"office": "X"}, "rows": rows})
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 2
    text = _text(pdf)
    assert "Testudo hermanni 7" in text and "Testudo hermanni 0" in text


@pytest.mark.django_db
def test_sct5_from_death(keeper, user, hermanni):
    res = services.register_birth(keeper=keeper, user=user, species=hermanni, birth_date=date(2024, 10, 18),
                                  rows=[services.NewbornSpec(quantity=9)])
    services.mark_protocolled(res.declaration, "1234 (10.100-1)", date(2024, 10, 31))
    decl = services.register_death(keeper=keeper, user=user, specimen=res.specimens[0], quantity=1,
                                   death_date=date(2025, 7, 20))
    fields = _fields(render_declaration(decl))
    assert fields["Campo di testo 7_2"] == "Mario Rossi"
    assert fields["Campo di testo 7_11"] == "Testudo hermanni n. 1"
    assert fields["Campo di testo 7_14"] == "1234 (10.100-1) - 31/10/2024"
    assert fields["Campo di testo 7_6"] == "AB1234567"


@pytest.mark.parametrize("kind", ["SCT1B", "SCT3", "CESSB", "LOSS", "SITE", "MARK"])
def test_other_kinds_render(kind):
    from apps.pdfforms.formdata import FORM_SPECS

    spec = FORM_SPECS[kind]
    fields = {f.key: (True if f.kind == "bool" else f"val-{f.key}") for f in spec.fields}
    rows = [{c: f"r-{c}" for c, _ in spec.row_columns}]
    pdf = render_pdf(kind, {"fields": fields, "rows": rows})
    text = _text(pdf)
    assert "val-place_date" in text
    assert f"r-{spec.row_columns[0][0]}" in text


def test_sct5_is_generated_not_shipped():
    from apps.pdfforms.sct5_template import FIELDS, build_sct5

    assert not (TEMPLATES / "sct5.pdf").exists()
    reader = PdfReader(io.BytesIO(build_sct5()))
    assert set(reader.get_fields()) == set(FIELDS)
    text = reader.pages[0].extract_text()
    assert "MODELLO SCT5" in text and "RESTITUISCE" in text
