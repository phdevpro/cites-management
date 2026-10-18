from datetime import date

import pytest
from django.contrib.auth.models import User

from apps.accounts.models import CitesOffice, DetentionSite, Keeper, Membership
from apps.species.models import Species
from apps.vault import services as vault
from apps.vault.context import KeyRing, using

PASSPHRASE = "test passphrase 123"


@pytest.fixture(autouse=True)
def _vault_settings(settings, tmp_path):
    settings.VAULT_SCRYPT_N = 2 ** 10  # fast KDF in tests
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture(autouse=True)
def keyring():
    """Fresh key ring per test (what the middleware provides per request)."""
    r = KeyRing()
    with using(r):
        yield r


def make_vault_user(username, passphrase=PASSPHRASE):
    user = User.objects.create_user(username, f"{username}@example.com", "pw-test-123")
    private, code = vault.create_user_key(user, passphrase)
    vault.confirm_recovery(user, code)
    user.private_key = private
    return user


def unlock_client(client, user):
    """Log in and set the encrypted unlock cookie, as after entering the passphrase."""
    client.force_login(user)
    ring = vault.keyring_for(user, user.private_key)
    client.cookies[vault.COOKIE_NAME] = vault.dump_cookie(ring, client.session.session_key)
    return client


@pytest.fixture
def office(db):
    return CitesOffice.objects.create(name="Nucleo CITES Test", city="Testcity", address="Via Prova 1 - 00100 Testcity")


@pytest.fixture
def keeper(db, office, keyring):
    k = Keeper(
        first_name="Mario", last_name="Rossi", birth_place="Udine", birth_province="UD", birth_date=date(1980, 2, 1),
        address="Via Roma 1", postal_code="33100", city="Udine", province="UD", phone="333 0000000",
        id_doc_number="AB1234567", cites_office=office,
    )
    k.dek = vault.new_keeper_key(k)
    k.save()
    keyring.keeper_keys[k.pk] = k.key_id
    DetentionSite.objects.create(keeper=k, address="Via Roma 1", postal_code="33100", city="Udine", province="UD")
    return k


@pytest.fixture
def user(db, keeper):
    u = make_vault_user("mario")
    vault.share_with(Membership.objects.create(user=u, keeper=keeper, role="owner"), keeper.dek)
    return u


@pytest.fixture
def client_logged(client, user):
    return unlock_client(client, user)


@pytest.fixture
def hermanni(db):
    return Species.objects.create(scientific_name="Testudo hermanni", common_name="Testuggine di Hermann", eu_annex="A")


@pytest.fixture
def python_regius(db):
    return Species.objects.create(scientific_name="Python regius", common_name="Pitone reale", eu_annex="B")
