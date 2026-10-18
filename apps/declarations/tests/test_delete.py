from datetime import date

import pytest

from apps.declarations import services
from apps.declarations.models import Declaration
from apps.registry.models import CitesDocument, Counterparty, RegisterEntry, Specimen


def _net(species):
    """Animals of a species in the register after corrections (carico - scarico)."""
    total = 0
    for e in RegisterEntry.objects.filter(species=species):
        total += e.quantity if e.direction == "carico" else -e.quantity
    return total


@pytest.fixture
def birth(keeper, user, hermanni):
    res = services.register_birth(keeper=keeper, user=user, species=hermanni, birth_date=date(2024, 10, 18),
                                  rows=[services.NewbornSpec(quantity=9)])
    services.mark_protocolled(res.declaration, "1234 (10.100-1)", date(2024, 10, 31))
    return res


@pytest.mark.django_db
def test_delete_birth_removes_animals_and_corrects_register(client_logged, birth, hermanni):
    decl = birth.declaration
    assert _net(hermanni) == 9
    resp = client_logged.post(f"/denunce/{decl.pk}/elimina/", follow=True)
    assert "rimossi 9 esemplari" in resp.content.decode()
    assert not Declaration.objects.exists() and not Specimen.objects.exists()
    assert "1234 (10.100-1)" not in [d.number for d in CitesDocument.objects.all()]  # numbers are encrypted
    assert _net(hermanni) == 0
    assert RegisterEntry.objects.filter(cause="rettifica").count() == 1  # history kept, cancelled


@pytest.mark.django_db
def test_birth_blocked_until_later_death_deleted(client_logged, keeper, user, birth, hermanni):
    death = services.register_death(keeper=keeper, user=user, specimen=birth.specimens[0], quantity=1,
                                    death_date=date(2025, 7, 20))
    resp = client_logged.post(f"/denunce/{birth.declaration.pk}/elimina/", follow=True)
    assert "Comunicazione di decesso" in resp.content.decode() and Declaration.objects.count() == 2

    client_logged.post(f"/denunce/{death.pk}/elimina/")
    lot = Specimen.objects.get()
    assert lot.quantity == 9 and lot.is_alive  # dead part rejoined the lot
    assert _net(hermanni) == 9
    client_logged.post(f"/denunce/{birth.declaration.pk}/elimina/")
    assert not Specimen.objects.exists() and _net(hermanni) == 0


@pytest.mark.django_db
def test_delete_completed_transfer_brings_animals_back(client_logged, keeper, user, birth, hermanni):
    buyer = Counterparty.objects.create(keeper=keeper, first_name="Luigi", last_name="Verdi")
    decl = services.start_transfer(keeper=keeper, user=user, counterparty=buyer, transfer_date=date(2025, 9, 1),
                                   lines=[services.TransferLine(specimen=birth.specimens[0], quantity=4)])
    services.complete_transfer(declaration=decl, user=user, completed_on=date(2025, 9, 21),
                               certificate_number="IT/CE/2025/XX/00001", certificate_date=date(2025, 9, 20))
    assert _net(hermanni) == 5
    client_logged.post(f"/denunce/{decl.pk}/elimina/")
    assert Specimen.objects.get().quantity == 9 and Specimen.objects.get().transferred_to is None
    assert "IT/CE/2025/XX/00001" not in [d.number for d in CitesDocument.objects.all()]
    assert _net(hermanni) == 9


@pytest.mark.django_db
def test_bulk_delete_handles_dependencies(client_logged, keeper, user, birth, hermanni):
    death = services.register_death(keeper=keeper, user=user, specimen=birth.specimens[0], quantity=2,
                                    death_date=date(2025, 7, 20))
    resp = client_logged.post("/denunce/elimina/", {"ids": [str(birth.declaration.pk), str(death.pk)]}, follow=True)
    assert "Eliminate 2 pratiche" in resp.content.decode()
    assert not Declaration.objects.exists() and not Specimen.objects.exists() and _net(hermanni) == 0


@pytest.mark.django_db
def test_imported_document_goes_back_to_review(client_logged, keeper, birth):
    from apps.importer.models import ImportBatch, ImportedFile

    batch = ImportBatch.objects.create(keeper=keeper)
    f = ImportedFile.objects.create(
        batch=batch, keeper=keeper, original_name="n.pdf", sha256="x", status="done", declaration=birth.declaration,
        parsed={"ai": True, "documents": [{"type": "birth_declaration", "confidence": 1,
                                           "result": {"status": "created", "declaration": birth.declaration.pk}}]})
    client_logged.post(f"/denunce/{birth.declaration.pk}/elimina/")
    f.refresh_from_db()
    assert f.status == "parsed" and f.declaration is None
    assert f.parsed["documents"][0]["result"]["status"] == "review"


@pytest.mark.django_db
def test_cannot_delete_other_keepers_declaration(client, birth):
    from apps.accounts.models import Keeper, Membership
    from apps.vault import services as vault
    from conftest import make_vault_user, unlock_client

    other_keeper = Keeper(first_name="A", last_name="B")
    dek = vault.new_keeper_key(other_keeper)
    other_keeper.save()
    intruder = make_vault_user("intruder2")
    vault.share_with(Membership.objects.create(user=intruder, keeper=other_keeper), dek)
    unlock_client(client, intruder)
    assert client.post(f"/denunce/{birth.declaration.pk}/elimina/").status_code == 404
    client.post("/denunce/elimina/", {"ids": [str(birth.declaration.pk)]})
    assert Declaration.objects.filter(pk=birth.declaration.pk).exists()
