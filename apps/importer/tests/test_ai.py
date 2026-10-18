"""AI import pipeline with a fake Regolo (OpenAI-compatible) client: no network, no cost."""

import io
import json
import zipfile
from datetime import date
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw

from apps.declarations.models import Declaration, Payment
from apps.importer import ai
from apps.importer.models import ImportBatch, ImportedFile
from apps.registry.models import Specimen
from apps.pdfforms.render import render_pdf

ID_TEXT = "REPUBBLICA ITALIANA CARTA D'IDENTITA COGNOME BIANCHI NOME LUIGI"


def _png(label: str) -> bytes:
    img = Image.new("RGB", (400, 200), "white")
    ImageDraw.Draw(img).text((10, 10), label, fill="black")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _scan_pdf(labels) -> bytes:
    """Image-only PDF (no text layer), one page per label."""
    pages = [Image.open(io.BytesIO(_png(lbl))).convert("RGB") for lbl in labels]
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:])
    return buf.getvalue()


def _doc(**kw):
    base = {"type": "other", "relates_to": "other", "direction": "", "pages": [1], "confidence": 0.95,
            "species": "", "quantity": 0, "event_date": "", "document_date": "", "protocol_number": "",
            "certificate_number": "", "references": [], "microchips": [], "counterparty_name": "",
            "counterparty_address": "", "amount_eur": 0, "breeding_group": "", "office": "Trieste", "summary": ""}
    base.update(kw)
    return base


# what the extraction model "reads" in each file (keyed by file name)
ANSWERS = {
    "nascita_2024.pdf": [_doc(type="birth_declaration", relates_to="birth", species="Testudo hermanni", quantity=9,
                              event_date="2024-10-18", document_date="2024-10-26", breeding_group="PROT 123 DEL 1999",
                              summary="Denuncia di nascita di 9 Testudo hermanni")],
    "DC_1234 (10.100-1) DN n. 9.pdf": [_doc(type="office_reply", relates_to="birth", species="Testudo hermanni",
                                            quantity=9, document_date="2024-10-31", protocol_number="1234 (10.100-1)",
                                            summary="Presa d'atto della denuncia di nascita")],
    "decesso_2025.pdf": [_doc(type="death_declaration", relates_to="death", species="Testudo hermanni", quantity=1,
                              event_date="2025-07-20", document_date="2025-07-20",
                              references=["1234 10/100-1 - 31/10/2024"], summary="Decesso di 1 Testudo hermanni")],
    "pagamento.pdf": [_doc(type="payment_receipt", relates_to="payment", amount_eur=15.49, document_date="2024-09-10",
                           summary="Ricevuta W802")],
    "pacchetto.pdf": [_doc(type="office_reply", relates_to="death", species="Testudo hermanni", quantity=1,
                           document_date="2025-07-25", protocol_number="11.22 (3333)", pages=[1],
                           summary="Presa d'atto del decesso")],
    "dubbio.pdf": [_doc(type="birth_declaration", relates_to="birth", species="Testudo hermanni", quantity=3,
                        event_date="2023-09-01", confidence=0.4, summary="Denuncia illeggibile")],
}


class FakeRegolo:
    def __init__(self, fail_extract=False):
        self.calls = []
        self.fail_extract = fail_extract
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, model, messages, **kwargs):
        self.calls.append({"model": model, "messages": messages, **kwargs})
        if model == "deepseek-ocr-2":
            return self._reply("Nucleo CITES Trieste - testo letto dall'OCR della pagina")
        if self.fail_extract:
            raise RuntimeError("quota exceeded")
        user = messages[-1]["content"]
        name = next(n for n in ANSWERS if n in user)
        return self._reply(json.dumps({"documents": ANSWERS[name]}))

    @staticmethod
    def _reply(text):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


@pytest.fixture
def regolo(settings, monkeypatch, keeper):
    settings.REGOLO_API_KEY = ""  # the key lives on the keeper profile, encrypted
    settings.AI_OCR_MODEL = "deepseek-ocr-2"
    settings.AI_EXTRACT_MODEL = "qwen3.5-122b"
    keeper.ai_api_key = "profile-key"
    keeper.save(update_fields=["ai_api_key"])
    fake = FakeRegolo()

    def client(api_key):
        assert api_key in ("profile-key", "new-key")
        return fake

    monkeypatch.setattr(ai, "client", client)
    # local OCR (identity filter): the second page of the bundle is an ID card
    monkeypatch.setattr(ai, "_local_ocr", lambda png: ID_TEXT if b"ID-PAGE" in png else "pagina normale")
    return fake


def _upload(client, files: dict):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return client.post("/importa/", {"archive": SimpleUploadedFile("Archive.zip", buf.getvalue()), "label": "AI"})


@pytest.fixture
def id_page_marker(monkeypatch):
    """Make the rendered PNG of the ID page recognisable by the fake local OCR."""
    real = ai.render_pages

    def render(path, max_pages):
        pages = real(path, max_pages)
        if "pacchetto" in str(path) or len(pages) == 2:
            n, png, text = pages[1]
            pages[1] = (n, png + b"ID-PAGE", text)
        return pages

    monkeypatch.setattr(ai, "render_pages", render)


@pytest.mark.django_db
def test_archive_becomes_records_automatically(client_logged, keeper, hermanni, regolo, id_page_marker):
    birth_pdf = render_pdf("SCT1A", {"fields": {"place_date": "Udine 26/10/2024"},
                                     "rows": [{"scientific_name": "n9 - TESTUDO HERMANNI", "birth_date": "18/10/2024"}]},
                           flatten=True)
    files = {
        "2024/nascita_2024.pdf": birth_pdf,
        "2024/DC_1234 (10.100-1) DN n. 9.pdf": _scan_pdf(["reply"]),
        "2025/decesso_2025.pdf": _scan_pdf(["death"]),
        "2024/pagamento.pdf": _scan_pdf(["receipt"]),
        "2025/pacchetto.pdf": _scan_pdf(["reply death", "carta identita"]),
        "2023/dubbio.pdf": _scan_pdf(["blurry"]),
    }
    _upload(client_logged, files)
    batch = ImportBatch.objects.get()

    # births → lot of 9 with protocol from the office reply
    birth = Declaration.objects.get(kind="SCT1A")
    assert birth.imported and birth.status == "protocolled" and birth.protocol_number == "1234 (10.100-1)"
    # death matched to that lot through the referenced protocol, then acknowledged by the bundle's reply
    death = Declaration.objects.get(kind="SCT5")
    assert death.event_date == date(2025, 7, 20) and death.protocol_number == "11.22 (3333)"
    assert Specimen.objects.get(status="dead").split_from.quantity == 8
    assert str(Payment.objects.get().amount) == "15.49"
    # uncertain reading → left for the user, nothing created
    dubbio = next(f for f in batch.files.all() if f.original_name == "dubbio.pdf")
    assert dubbio.status == "parsed" and dubbio.parsed["documents"][0]["result"]["status"] == "review"
    assert not Declaration.objects.filter(event_date=date(2023, 9, 1)).exists()
    others = [f for f in batch.files.all() if f.original_name != "dubbio.pdf"]
    assert all(f.status in ("done", "archived") for f in others), [(f.original_name, f.status) for f in others]

    # the identity page was never sent: no OCR call for it, its text absent from every request
    bundle = next(f for f in batch.files.all() if f.original_name == "pacchetto.pdf")
    assert bundle.parsed["identity_pages"] == [2]
    assert any(d["type"] == "identity_document" for d in bundle.parsed["documents"])
    sent = json.dumps([c["messages"] for c in regolo.calls])
    assert "BIANCHI" not in sent and "CARTA D'IDENTITA" not in sent
    ocr_calls = [c for c in regolo.calls if c["model"] == "deepseek-ocr-2"]
    assert len(ocr_calls) == 5  # 4 single-page scans + page 1 of the bundle; text-layer PDF needs no OCR
    extract = next(c for c in regolo.calls if c["model"] == "qwen3.5-122b")
    assert extract["response_format"]["type"] == "json_schema" and extract["temperature"] == 0

    # results visible to the user
    page = client_logged.get(f"/importa/lotto/{batch.pk}/").content.decode()
    assert "Denuncia di nascita" in page and "da verificare" in page and "Riapplica automaticamente" in page


@pytest.mark.django_db
def test_ambiguous_death_waits_then_manual_resolution(client_logged, keeper, user, hermanni, regolo):
    from apps.declarations import services

    for born in (date(2022, 9, 1), date(2023, 9, 1)):
        services.register_birth(keeper=keeper, user=user, species=hermanni, birth_date=born,
                                rows=[services.NewbornSpec(quantity=5)])
    ANSWERS["decesso_x.pdf"] = [_doc(type="death_declaration", relates_to="death", species="Testudo hermanni",
                                     quantity=1, event_date="2025-07-20")]
    _upload(client_logged, {"decesso_x.pdf": _scan_pdf(["death"])})
    f = ImportedFile.objects.get()
    res = f.parsed["documents"][0]["result"]
    assert res["status"] == "review" and "candidati" in res["message"]
    assert not Specimen.objects.filter(status="dead").exists()

    lot = Specimen.objects.order_by("birth_date").first()
    resp = client_logged.get(f"/importa/file/{f.pk}/")
    assert "Comunicazione di decesso" in resp.content.decode()
    client_logged.post(f"/importa/file/{f.pk}/", {"doc_index": "0", "action": "death", "species": hermanni.pk,
                                                 "quantity": "1", "event_date": "2025-07-20",
                                                 "specimen": lot.pk})
    f.refresh_from_db()
    assert f.status == "done" and f.parsed["documents"][0]["result"]["status"] == "created"
    assert Specimen.objects.get(status="dead").split_from == lot


@pytest.mark.django_db
def test_ai_failure_falls_back_to_local_reader(client_logged, keeper, hermanni, regolo):
    regolo.fail_extract = True
    pdf = render_pdf("SCT1A", {"fields": {"place_date": "Udine 26/10/2024"},
                               "rows": [{"scientific_name": "n9 - TESTUDO HERMANNI", "birth_date": "18/10/2024"}]},
                     flatten=False)
    _upload(client_logged, {"nascita_2024.pdf": pdf})
    f = ImportedFile.objects.get()
    assert f.method == "acroform" and f.detected_kind == "SCT1A"
    assert "Lettura AI non riuscita" in f.parsed["notes"][0]


@pytest.mark.django_db
def test_extraction_denied_reuses_ocr_text(client_logged, keeper, hermanni, regolo, monkeypatch):
    """Key enabled only for the OCR model: the OCR text is kept and parsed locally, no local OCR pass."""
    def denied(*a, **kw):
        raise RuntimeError("Error code: 401 - key not allowed to access model. This key can only access "
                           "models=['deepseek-ocr-2']. Tried to access qwen3.5-122b")

    monkeypatch.setattr(ai, "extract_documents", denied)
    import apps.importer.services as svc

    monkeypatch.setattr(svc, "extract", lambda p: pytest.fail("local OCR must not run again"))
    _upload(client_logged, {"2024/DC_1234 (10.100-1) DN n. 9 Testudo hermanni.pdf": _scan_pdf(["reply"])})
    f = ImportedFile.objects.get()
    assert f.method == "ocr-ai" and "Nucleo CITES Trieste" in f.text
    assert "non è abilitata al modello qwen3.5-122b" in f.parsed["notes"][0]
    assert f.detected_kind == "REPLY"


def test_explain_regolo_errors():
    msg = ai.explain(RuntimeError("key not allowed to access model. This key can only access "
                                  "models=['deepseek-ocr-2']. Tried to access qwen3.5-122b"))
    assert "qwen3.5-122b" in msg and "dashboard di Regolo" in msg


@pytest.mark.django_db
def test_profile_key_is_encrypted_and_owner_only(client, client_logged, keeper, user, regolo):
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT ai_api_key FROM accounts_keeper WHERE id = %s", [keeper.pk])
        raw = cur.fetchone()[0]
    assert raw.startswith("enc1:") and "profile-key" not in raw
    page = client_logged.get("/account/detentore/").content.decode()
    assert "Lettura AI dei documenti" in page and "profile-key" not in page  # never echoed back
    resp = client_logged.post("/account/detentore/ai/", {"api_key": "new-key"}, follow=True)
    assert "Verifica chiave" in resp.content.decode()

    from apps.accounts.models import Membership
    from apps.vault import services as vault
    from conftest import make_vault_user, unlock_client

    editor = make_vault_user("editor")
    vault.share_with(Membership.objects.create(user=editor, keeper=keeper, role="editor"), keeper.dek)
    unlock_client(client, editor)
    assert client.post("/account/detentore/ai/", {"remove": "on"}).status_code == 403


@pytest.mark.django_db
def test_check_key_probes_both_models(regolo):
    regolo.fail_extract = True
    problems = ai.check_key("profile-key")
    assert len(problems) == 1 and problems[0].startswith("qwen3.5-122b")
    assert {c["model"] for c in regolo.calls} == {"deepseek-ocr-2", "qwen3.5-122b"}


@pytest.mark.django_db
def test_without_key_ai_is_off(client_logged, keeper, settings, monkeypatch):
    settings.REGOLO_API_KEY = ""
    monkeypatch.setattr(ai, "client", lambda key: pytest.fail("AI must not be called without a key"))
    _upload(client_logged, {"x.pdf": _scan_pdf(["page"])})
    assert ImportedFile.objects.get().method != "ai"


def test_identity_detection():
    assert ai.looks_like_identity(ID_TEXT)
    assert ai.looks_like_identity("P<ITABIANCHI<<LUIGI<<<<<<<<<<<<<<<<<<<<<<<")
    assert not ai.looks_like_identity("Nucleo CITES Trieste Prot. 32/118-3 Testudo hermanni")


def test_clean_drops_identity_data_and_bad_values():
    out = ai._clean({"type": "identity_document", "counterparty_name": "Luigi Bianchi", "confidence": "2",
                     "microchips": ["380 260 000 000 001", "123"], "event_date": "18/10/2024", "quantity": "x"})
    assert out["counterparty_name"] == "" and out["confidence"] == 1.0
    assert out["microchips"] == ["380260000000001"] and out["event_date"] == "" and out["quantity"] == 0



@pytest.mark.django_db
def test_reapply_does_not_duplicate_attachments(client_logged, keeper, hermanni, regolo):
    from apps.importer.autoapply import auto_apply_batch

    birth_pdf = render_pdf("SCT1A", {"fields": {"place_date": "Udine 26/10/2024"},
                                     "rows": [{"scientific_name": "n9 - TESTUDO HERMANNI", "birth_date": "18/10/2024"}]},
                           flatten=True)
    _upload(client_logged, {"2024/nascita_2024.pdf": birth_pdf})
    batch = ImportBatch.objects.get()
    decl = Declaration.objects.get(kind="SCT1A")
    assert decl.attachments.count() == 1
    f = batch.files.get()
    f.parsed["documents"][0]["result"] = {"status": "review"}  # force a second pass on the same document
    f.status = "parsed"
    f.save()
    auto_apply_batch(batch, keeper.memberships.first().user)
    assert decl.attachments.count() == 1 and Declaration.objects.filter(kind="SCT1A").count() == 1
