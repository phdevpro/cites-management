from datetime import date
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from apps.declarations import services
from apps.declarations.emailtext import build_email
from apps.registry.models import Counterparty


@pytest.fixture
def birth(keeper, user, hermanni):
    return services.register_birth(keeper=keeper, user=user, species=hermanni, birth_date=date(2024, 10, 18),
                                   rows=[services.NewbornSpec(quantity=9)]).declaration


@pytest.mark.django_db
def test_birth_email(birth, office):
    office.pec = "cites.test@pec.example"
    office.save()
    birth.refresh_from_db()
    mail = build_email(birth)
    assert mail["to"] == "cites.test@pec.example"
    assert mail["subject"] == ("Denuncia di nascita in cattività (art. 8-bis L. 150/1992) - "
                               "Testudo hermanni (n. 9) - nati il 18/10/2024")
    assert mail["body"].startswith("Spett.le Nucleo CITES Test,")
    assert "Modello SCT1/A" in mail["body"] and "Mario Rossi" in mail["body"]
    assert "(da firmare)" in mail["body"] and "copia del documento d'identità del dichiarante" in mail["body"]
    q = parse_qs(urlparse(mail["mailto"]).query)
    assert unquote(urlparse(mail["mailto"]).path) == "cites.test@pec.example"
    assert q["subject"][0] == mail["subject"] and q["body"][0] == mail["body"]


@pytest.mark.django_db
def test_death_and_transfer_emails(keeper, user, birth):
    sp = birth.items.get().specimen
    death = services.register_death(keeper=keeper, user=user, specimen=sp, quantity=1, death_date=date(2025, 7, 20))
    body = build_email(death)["body"]
    assert "decesso, avvenuto il 20/07/2025" in body and "certificati originali" in body
    buyer = Counterparty.objects.create(keeper=keeper, first_name="Luigi", last_name="Verdi")
    transfer = services.start_transfer(keeper=keeper, user=user, counterparty=buyer, transfer_date=date(2025, 9, 1),
                                       lines=[services.TransferLine(specimen=sp, quantity=2)])
    mail = build_email(transfer)
    assert mail["subject"].startswith("Richiesta certificato di spostamento")
    assert "Luigi Verdi" in mail["body"] and "W802" in mail["body"]


@pytest.mark.django_db
def test_signed_pdf_with_id_changes_attachment_list(birth, keeper):
    from django.core.files.base import ContentFile

    keeper.signature.save("f.png", ContentFile(b"png"))
    keeper.id_doc_file.save("ci.pdf", ContentFile(b"%PDF"))
    birth.refresh_from_db()
    body = build_email(birth)["body"]
    assert "compilata e firmata, con copia del documento d'identità in coda" in body
    assert "- copia del documento d'identità del dichiarante" not in body


@pytest.mark.django_db
def test_detail_page_shows_email_card(client_logged, birth):
    page = client_logged.get(f"/denunce/{birth.pk}/").content.decode()
    assert "Email per l&#x27;ufficio CITES" in page or "Email per l'ufficio CITES" in page
    assert 'data-copy="email-body"' in page and 'href="mailto:' in page
