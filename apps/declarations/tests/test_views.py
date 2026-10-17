from datetime import date

import pytest

from apps.declarations import services
from apps.registry.models import Counterparty, Specimen


@pytest.mark.django_db
def test_pages_render(client_logged, keeper, user, hermanni):
    res = services.register_birth(keeper=keeper, user=user, species=hermanni, birth_date=date(2024, 10, 18),
                                  rows=[services.NewbornSpec(quantity=9)])
    sp = res.specimens[0]
    Counterparty.objects.create(keeper=keeper, first_name="L", last_name="V")
    urls = ["/", "/guida/", "/esemplari/", f"/esemplari/{sp.pk}/", f"/esemplari/{sp.pk}/genealogia/",
            "/esemplari/nuovo/", "/esemplari/controparti/", "/esemplari/documenti/", "/esemplari/registro/",
            "/esemplari/registro/export/pdf/", "/esemplari/registro/export/xlsx/", "/denunce/", "/denunce/nascita/",
            "/denunce/decesso/", "/denunce/cessione/", "/denunce/smarrimento/", f"/denunce/{res.declaration.pk}/",
            f"/denunce/{res.declaration.pk}/modulo/", f"/denunce/{res.declaration.pk}/anteprima/",
            f"/denunce/{res.declaration.pk}/busta/", f"/denunce/{res.declaration.pk}/pacchetto/",
            "/denunce/pagamenti/", "/denunce/pagamenti/nuovo/", "/importa/", "/account/detentore/"]
    for url in urls:
        resp = client_logged.get(url)
        assert resp.status_code == 200, url


@pytest.mark.django_db
def test_birth_wizard_and_generate(client_logged, keeper, hermanni):
    resp = client_logged.post("/denunce/nascita/", {
        "species": hermanni.pk, "birth_date": "2025-10-04", "breeding_group": "PROT 123 DEL 1999",
        "rows-TOTAL_FORMS": "1", "rows-INITIAL_FORMS": "0", "rows-MIN_NUM_FORMS": "1", "rows-MAX_NUM_FORMS": "50",
        "rows-0-quantity": "7", "rows-0-sex": "I",
    })
    assert resp.status_code == 302
    sp = Specimen.objects.get()
    assert sp.quantity == 7
    decl = sp.declaration_items.get().declaration
    resp = client_logged.post(f"/denunce/{decl.pk}/genera/")
    decl.refresh_from_db()
    assert decl.status == "generated" and decl.pdf.name.endswith(".pdf")


@pytest.mark.django_db
def test_edit_form_data_overrides(client_logged, keeper, user, hermanni):
    res = services.register_birth(keeper=keeper, user=user, species=hermanni, birth_date=date(2024, 10, 18),
                                  rows=[services.NewbornSpec(quantity=9)])
    decl = res.declaration
    page = client_logged.get(f"/denunce/{decl.pk}/modulo/").content.decode()
    assert "n. 9 - Testudo hermanni" in page
    resp = client_logged.post(f"/denunce/{decl.pk}/modulo/", {
        "office": keeper.cites_office_id, "event_date": "2024-10-18", "place": "Udine", "signed_on": "2024-10-26",
        "f__office": "Trieste", "f__declarant": "Custom", "f__place_date": "Udine 26/10/2024",
        "n_rows": "1", "r__0__scientific_name": "n9 - TESTUDO HERMANNI", "r__0__birth_date": "18/10/2024",
    })
    assert resp.status_code == 302
    decl.refresh_from_db()
    assert decl.data["form"]["fields"]["declarant"] == "Custom"
    assert decl.data["form"]["rows"][0]["scientific_name"] == "n9 - TESTUDO HERMANNI"
