from datetime import date

import pytest
from django.contrib.auth.models import User

from apps.accounts.models import CitesOffice, DetentionSite, Keeper, Membership
from apps.species.models import Species


@pytest.fixture
def office(db):
    return CitesOffice.objects.create(name="Nucleo CITES Test", city="Testcity", address="Via Prova 1 - 00100 Testcity")


@pytest.fixture
def keeper(db, office):
    k = Keeper.objects.create(
        first_name="Mario", last_name="Rossi", birth_place="Udine", birth_province="UD", birth_date=date(1980, 2, 1),
        address="Via Roma 1", postal_code="33100", city="Udine", province="UD", phone="333 0000000",
        id_doc_number="AB1234567", cites_office=office,
    )
    DetentionSite.objects.create(keeper=k, address="Via Roma 1", postal_code="33100", city="Udine", province="UD")
    return k


@pytest.fixture
def user(db, keeper):
    u = User.objects.create_user("mario", "mario@example.com", "pw-test-123")
    Membership.objects.create(user=u, keeper=keeper, role="owner")
    return u


@pytest.fixture
def client_logged(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def hermanni(db):
    return Species.objects.create(scientific_name="Testudo hermanni", common_name="Testuggine di Hermann", eu_annex="A")


@pytest.fixture
def python_regius(db):
    return Species.objects.create(scientific_name="Python regius", common_name="Pitone reale", eu_annex="B")
