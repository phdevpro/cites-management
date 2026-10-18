import io
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw
from pypdf import PdfReader

from apps.declarations import services
from apps.pdfforms.render import render_pdf
from apps.pdfforms.signing import SIGNATURE_BOXES, prepare_signature


def scribble(bg="white") -> bytes:
    img = Image.new("RGB", (600, 200), bg)
    d = ImageDraw.Draw(img)
    d.line([(40, 150), (120, 40), (200, 160), (300, 50), (420, 150), (560, 60)], fill="navy", width=8)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def id_card_jpg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (856, 540), "lightblue").save(buf, "JPEG")
    return buf.getvalue()


def _images_on(page) -> int:
    return len(page.images)


def test_prepare_signature_makes_background_transparent():
    out = Image.open(io.BytesIO(prepare_signature(scribble())))
    assert out.mode == "RGBA"
    assert out.getpixel((0, 0))[3] == 0 or out.size[0] < 600  # cropped to the ink and/or transparent
    assert out.getchannel("A").getextrema()[1] == 255  # ink kept


@pytest.mark.parametrize("kind", ["SCT1A", "SCT1B", "SCT5", "SCT3", "CESSB", "LOSS"])
def test_signature_is_stamped_and_id_appended(kind):
    from apps.pdfforms.formdata import FORM_SPECS

    spec = FORM_SPECS[kind]
    data = {"fields": {f.key: ("x" if f.kind != "bool" else False) for f in spec.fields},
            "rows": [{c: "r" for c, _ in spec.row_columns}]}
    plain = PdfReader(io.BytesIO(render_pdf(kind, data)))
    signed = PdfReader(io.BytesIO(render_pdf(kind, data, signature=prepare_signature(scribble()),
                                             attachment=id_card_jpg(), attachment_name="ci.jpg")))
    assert len(signed.pages) == len(plain.pages) + 1  # ID card appended as one A4 page
    assert sum(_images_on(p) for p in signed.pages[:-1]) > sum(_images_on(p) for p in plain.pages)
    assert _images_on(signed.pages[-1]) == 1


def test_signature_on_every_copy_of_a_split_form():
    rows = [{"scientific_name": f"Testudo hermanni {i}"} for i in range(8)]  # 2 copies of SCT1A
    pdf = PdfReader(io.BytesIO(render_pdf("SCT1A", {"fields": {}, "rows": rows}, signature=prepare_signature(scribble()))))
    assert len(pdf.pages) == 2 and all(_images_on(p) == 1 for p in pdf.pages)


def test_pdf_id_document_pages_appended():
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, "fronte")
    c.showPage()
    c.drawString(100, 700, "retro")
    c.save()
    pdf = PdfReader(io.BytesIO(render_pdf("SCT5", {"fields": {}, "rows": []}, attachment=buf.getvalue(),
                                          attachment_name="ci.pdf")))
    assert len(pdf.pages) == 3 and "retro" in pdf.pages[2].extract_text()


def test_unreadable_attachment_is_skipped():
    pdf = PdfReader(io.BytesIO(render_pdf("SCT5", {"fields": {}, "rows": []}, attachment=b"%PDF-broken",
                                          attachment_name="ci.pdf")))
    assert len(pdf.pages) == 1


def test_signature_boxes_inside_page():
    for kind, (x0, y0, x1, y1) in SIGNATURE_BOXES.items():
        assert 0 < x0 < x1 < 595 and 0 < y0 < y1 < 842, kind


@pytest.mark.django_db
def test_generate_asks_then_uses_uploaded_signature_and_id(client_logged, keeper, user, hermanni, settings):
    from pathlib import Path

    res = services.register_birth(keeper=keeper, user=user, species=hermanni, birth_date=date(2024, 10, 18),
                                  rows=[services.NewbornSpec(quantity=9)])
    decl = res.declaration
    assert client_logged.post(f"/denunce/{decl.pk}/genera/").url.endswith("/firma-e-allegati/")
    page = client_logged.get(f"/denunce/{decl.pk}/firma-e-allegati/").content.decode()
    assert "non c'è ancora una firma" in page
    # ticked but nothing uploaded: refused with an explanation
    resp = client_logged.post(f"/denunce/{decl.pk}/firma-e-allegati/", {"include_signature": "on"})
    assert "Carica la firma oppure togli la spunta" in resp.content.decode()
    resp = client_logged.post(f"/denunce/{decl.pk}/firma-e-allegati/", {
        "include_signature": "on", "include_id": "on",
        "signature": SimpleUploadedFile("firma.jpg", scribble(), content_type="image/png"),
        "id_doc": SimpleUploadedFile("ci.jpg", id_card_jpg(), content_type="image/jpeg")})
    assert resp.status_code == 302
    decl.refresh_from_db()
    keeper.refresh_from_db()
    assert decl.status == "generated" and keeper.signature and keeper.id_doc_file
    from apps.vault.storage import read_plain

    pdf = PdfReader(io.BytesIO(read_plain(decl.pdf)))
    assert len(pdf.pages) == 2 and _images_on(pdf.pages[0]) == 1
    # stored encrypted, never in clear on disk
    for name in (keeper.signature.name, keeper.id_doc_file.name):
        assert (Path(settings.MEDIA_ROOT) / name).read_bytes().startswith(b"CITESENC1")
    # next declaration: nothing missing any more, generated straight away
    res2 = services.register_birth(keeper=keeper, user=user, species=hermanni, birth_date=date(2025, 10, 4),
                                   rows=[services.NewbornSpec(quantity=7)])
    assert client_logged.post(f"/denunce/{res2.declaration.pk}/genera/").url == f"/denunce/{res2.declaration.pk}/"


@pytest.mark.django_db
def test_only_owner_can_upload_signature(client, keeper, user, hermanni):
    from apps.accounts.models import Membership
    from apps.vault import services as vault
    from conftest import make_vault_user, unlock_client

    res = services.register_birth(keeper=keeper, user=user, species=hermanni, birth_date=date(2024, 10, 18),
                                  rows=[services.NewbornSpec(quantity=1)])
    editor = make_vault_user("ed")
    vault.share_with(Membership.objects.create(user=editor, keeper=keeper, role="editor"), keeper.dek)
    unlock_client(client, editor)
    page = client.get(f"/denunce/{res.declaration.pk}/firma-e-allegati/").content.decode()
    assert "Solo il titolare può caricarla" in page and 'name="signature"' not in page
