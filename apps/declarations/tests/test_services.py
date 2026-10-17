from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError

from apps.declarations import services
from apps.declarations.models import Declaration
from apps.registry.models import CitesDocument, Counterparty, RegisterEntry, Specimen


@pytest.fixture
def birth(keeper, user, hermanni):
    return services.register_birth(keeper=keeper, user=user, species=hermanni, birth_date=date(2024, 10, 18),
                                   rows=[services.NewbornSpec(quantity=9)], breeding_group="PROT 123 DEL 1999")


def test_birth_creates_lot_declaration_and_carico(birth, keeper):
    decl = birth.declaration
    assert decl.kind == "SCT1A"
    assert decl.deadline == date(2024, 10, 28)
    lot = birth.specimens[0]
    assert lot.quantity == 9 and lot.origin == "born"
    entry = RegisterEntry.objects.get(specimen=lot)
    assert (entry.register_type, entry.direction, entry.quantity, entry.number) == ("EA", "carico", 9, 1)


def test_birth_annex_b_uses_sct1b(keeper, user, python_regius):
    res = services.register_birth(keeper=keeper, user=user, species=python_regius, birth_date=date(2025, 1, 1),
                                  rows=[services.NewbornSpec(quantity=3)])
    assert res.declaration.kind == "SCT1B"
    assert RegisterEntry.objects.get().register_type == "EB"


def test_death_splits_lot_and_cites_protocol(birth, keeper, user):
    lot = birth.specimens[0]
    services.mark_protocolled(birth.declaration, "1234 (10.100-1)", date(2024, 10, 31))
    decl = services.register_death(keeper=keeper, user=user, specimen=lot, quantity=1, death_date=date(2025, 7, 20))
    lot.refresh_from_db()
    assert lot.quantity == 8 and lot.status == "alive"
    dead = Specimen.objects.get(status="dead")
    assert dead.split_from == lot and dead.quantity == 1
    assert decl.kind == "SCT5"
    item = decl.items.get()
    assert item.document.number == "1234 (10.100-1)"
    scarico = RegisterEntry.objects.get(direction="scarico")
    assert scarico.carico_ref.specimen == lot


def test_death_too_many(birth, keeper, user):
    with pytest.raises(services.ServiceError):
        services.register_death(keeper=keeper, user=user, specimen=birth.specimens[0], quantity=10,
                                death_date=date(2025, 1, 1))


def test_transfer_annex_a_two_step(birth, keeper, user):
    buyer = Counterparty.objects.create(keeper=keeper, first_name="Luigi", last_name="Verdi")
    decl = services.start_transfer(keeper=keeper, user=user, counterparty=buyer, transfer_date=date(2025, 9, 1),
                                   lines=[services.TransferLine(specimen=birth.specimens[0], quantity=4)])
    assert decl.kind == "SCT3"
    part = decl.items.get().specimen
    assert part.quantity == 4 and part.status == "alive"  # still held until certificate
    services.complete_transfer(declaration=decl, user=user, completed_on=date(2025, 9, 21),
                               certificate_number="IT/CE/2025/TS/00001", certificate_date=date(2025, 9, 20))
    part.refresh_from_db()
    assert part.status == "transferred" and part.transferred_to == buyer
    assert CitesDocument.objects.get(doc_type="art9").specimens.get() == part
    decl.refresh_from_db()
    assert decl.status == "closed"
    assert RegisterEntry.objects.filter(direction="scarico", cause="vendita").count() == 1


def test_transfer_annex_b_immediate(keeper, user, python_regius):
    sp = services.register_acquisition(keeper=keeper, user=user, species=python_regius, quantity=1,
                                       acquired_on=date(2024, 1, 1), counterparty=None)
    buyer = Counterparty.objects.create(keeper=keeper, company_name="Rettili Srl")
    decl = services.start_transfer(keeper=keeper, user=user, counterparty=buyer, transfer_date=date(2025, 2, 1),
                                   lines=[services.TransferLine(specimen=sp)])
    sp.refresh_from_db()
    assert decl.kind == "CESSB" and sp.status == "transferred"


def test_mixed_annex_transfer_rejected(keeper, user, hermanni, python_regius):
    a = Specimen.objects.create(keeper=keeper, species=hermanni)
    b = Specimen.objects.create(keeper=keeper, species=python_regius)
    cp = Counterparty.objects.create(keeper=keeper, first_name="X")
    with pytest.raises(services.ServiceError):
        services.start_transfer(keeper=keeper, user=user, counterparty=cp, transfer_date=date.today(),
                                lines=[services.TransferLine(a), services.TransferLine(b)])


def test_register_is_append_only(birth):
    entry = RegisterEntry.objects.get()
    entry.notes = "changed"
    with pytest.raises(ValidationError):
        entry.save()
    with pytest.raises(ValidationError):
        entry.delete()


def test_marking_splits_one_from_lot(birth, keeper, user):
    decl = services.add_marking(keeper=keeper, user=user, specimen=birth.specimens[0], kind="microchip",
                                code="380260000000001", applied_on=date(2025, 6, 1))
    marked = decl.items.get().specimen
    assert marked.quantity == 1 and marked.markings.get().code == "380260000000001"
    assert decl.kind == "MARK"


def test_overdue(keeper, user, hermanni):
    res = services.register_birth(keeper=keeper, user=user, species=hermanni,
                                  birth_date=date.today() - timedelta(days=20), rows=[services.NewbornSpec()])
    assert res.declaration.is_overdue
    services.mark_sent(res.declaration, date.today(), "pec")
    assert not Declaration.objects.get().is_overdue
