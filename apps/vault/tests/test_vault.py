import hashlib
import re
from datetime import date
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import connection, transaction

from apps.accounts import terms
from apps.accounts.models import Keeper, Membership
from apps.declarations import services
from apps.declarations.models import Declaration
from apps.importer.models import file_sha256
from apps.registry.models import Counterparty, RegisterEntry, Specimen
from apps.vault import crypto
from apps.vault import services as vault
from apps.vault.context import KeyRing, VaultLocked, using
from apps.vault.fields import Locked
from apps.vault.storage import read_plain
from conftest import PASSPHRASE, make_vault_user, unlock_client

SECRETS = ["Mario", "Rossi", "AB1234567", "Udine", "Via Roma", "PROT 123", "Luigi", "Verdi", "380260000000001"]


def _dump_db() -> str:
    """Every text value in every table, as stored."""
    out = []
    with connection.cursor() as cur:
        for table in connection.introspection.table_names():
            cur.execute(f'SELECT * FROM "{table}"')
            for row in cur.fetchall():
                out.extend(str(v) for v in row if isinstance(v, str))
    return "\n".join(out)


def _populate(keeper, user, hermanni):
    res = services.register_birth(keeper=keeper, user=user, species=hermanni, birth_date=date(2024, 10, 18),
                                  rows=[services.NewbornSpec(quantity=9)], breeding_group="PROT 123 DEL 1999")
    services.add_marking(keeper=keeper, user=user, specimen=res.specimens[0], kind="microchip",
                         code="380260000000001")
    buyer = Counterparty.objects.create(keeper=keeper, first_name="Luigi", last_name="Verdi", id_doc_number="ZZ999")
    buyer.id_doc_file.save("Verdi Luigi CI.pdf", ContentFile(b"%PDF-1.4 Luigi Verdi passport"))
    decl = res.declaration
    decl.data = {"form": {"fields": {"declarant": "Mario Rossi, Udine"}, "rows": []}}
    decl.notes = "chiamare Mario"
    decl.save()
    from apps.pdfforms.render import render_declaration

    decl.pdf.save("SCT1A_rossi.pdf", ContentFile(render_declaration(decl)))
    return res, buyer, decl


@pytest.mark.django_db
def test_database_and_files_hold_no_personal_data(keeper, user, hermanni):
    keeper.id_doc_file.save("Rossi Mario carta identita.pdf", ContentFile(b"%PDF-1.4 Mario Rossi AB1234567"))
    res, buyer, decl = _populate(keeper, user, hermanni)

    dump = _dump_db()
    for secret in SECRETS:
        assert secret not in dump, secret
    assert "enc1:" in dump

    media = Path(settings.MEDIA_ROOT)
    files = [p for p in media.rglob("*") if p.is_file()]
    assert len(files) == 3
    for p in files:
        raw = p.read_bytes()
        assert raw.startswith(b"CITESENC1") and b"%PDF" not in raw
        assert re.fullmatch(r"[0-9a-f]{32}\.pdf", p.name), p.name  # no personal names in file names

    # still fully readable with the key
    k = Keeper.objects.get(pk=keeper.pk)
    assert (k.first_name, k.last_name, k.birth_date, k.id_doc_number) == ("Mario", "Rossi", date(1980, 2, 1), "AB1234567")
    assert read_plain(k.id_doc_file) == b"%PDF-1.4 Mario Rossi AB1234567"
    assert Declaration.objects.get(pk=decl.pk).data["form"]["fields"]["declarant"] == "Mario Rossi, Udine"
    assert read_plain(Declaration.objects.get(pk=decl.pk).pdf).startswith(b"%PDF")
    assert RegisterEntry.objects.filter(cause="nascita").first().counterparty == "nato in allevamento"
    assert Specimen.history.filter(breeding_group__startswith="enc1:").exists()  # history rows encrypted in DB
    assert Specimen.history.first().breeding_group == "PROT 123 DEL 1999"


@pytest.mark.django_db
def test_without_key_values_are_locked_and_preserved(keeper, user, hermanni):
    res, _, _ = _populate(keeper, user, hermanni)
    with using(KeyRing()):
        k = Keeper.objects.get(pk=keeper.pk)
        assert isinstance(k.first_name, Locked) and str(k.first_name) == "🔒"
        k.save()  # saving a locked object must not destroy the ciphertext
        with pytest.raises(VaultLocked), transaction.atomic():
            Specimen.objects.create(keeper=keeper, species=hermanni, name="new")  # never write clear text
        with pytest.raises(VaultLocked):
            read_plain(Keeper.objects.get(pk=keeper.pk).id_doc_file or res.declaration.pdf)
    assert Keeper.objects.get(pk=keeper.pk).first_name == "Mario"


@pytest.mark.django_db
def test_microchip_uniqueness_checked_in_code(keeper, user, hermanni):
    res, _, _ = _populate(keeper, user, hermanni)
    with pytest.raises(services.ServiceError):
        services.add_marking(keeper=keeper, user=user, specimen=res.specimens[0], kind="microchip",
                             code="380 260 000 000 001")


@pytest.mark.django_db
def test_import_fingerprint_is_keyed(keeper):
    data = ContentFile(b"some document")
    assert file_sha256(data, keeper) != hashlib.sha256(b"some document").hexdigest()


def test_wrap_unwrap_and_recovery_code():
    private, public = crypto.new_keypair()
    dek = crypto.random_key()
    assert crypto.unwrap(private, crypto.wrap_for(public, dek)) == dek
    other_private, _ = crypto.new_keypair()
    with pytest.raises(crypto.DecryptionError):
        crypto.unwrap(other_private, crypto.wrap_for(public, dek))
    code = crypto.new_recovery_code()
    assert re.fullmatch(r"([A-Z2-9]{4}-){7}[A-Z2-9]{4}", code)
    assert crypto.recovery_key(code.lower().replace("-", " ")) == crypto.recovery_key(code)


# --------------------------------------------------------------------------- flows through the web UI

@pytest.mark.django_db
def test_setup_recovery_unlock_flow(client):
    user = User.objects.create_user("new", "n@example.com", "pw-test-123")
    terms.record(user)
    client.force_login(user)
    assert client.get("/").url == "/vault/configura/"
    resp = client.post("/vault/configura/", {"passphrase": "short", "confirm": "short"})
    assert resp.status_code == 200 and b"almeno" in resp.content
    resp = client.post("/vault/configura/", {"passphrase": PASSPHRASE, "confirm": PASSPHRASE})
    code = re.search(r'id="code">([A-Z2-9-]+)<', resp.content.decode()).group(1)
    assert client.get("/").url == "/vault/recupero/"  # recovery key must be confirmed
    assert client.post("/vault/recupero/", {"code": "AAAA-BBBB"}).status_code == 200
    assert client.post("/vault/recupero/", {"code": code}).status_code == 302
    assert client.get("/").url == "/account/detentore/nuovo/"

    # create the keeper through the form: everything written encrypted
    resp = client.post("/account/detentore/nuovo/", {
        "first_name": "Carla", "last_name": "Neri", "id_doc_type": "CI",
        "site-address": "Via Verdi 9", "site-city": "Trieste", "site-is_default": "on",
    })
    assert resp.status_code == 302
    assert "Carla" not in _dump_db() and "Via Verdi" not in _dump_db()
    assert client.get("/").status_code == 200

    # new session: must unlock again; wrong passphrase rejected
    client.logout()
    client.force_login(user)
    assert client.get("/esemplari/").url.startswith("/vault/sblocca/")
    assert "errata" in client.post("/vault/sblocca/", {"passphrase": "wrong passphrase!!"}).content.decode()
    resp = client.post("/vault/sblocca/", {"passphrase": PASSPHRASE, "next": "/esemplari/"})
    assert resp.url == "/esemplari/"
    assert "Carla Neri" in client.get("/account/detentore/").content.decode()

    # forgotten passphrase → recovery key
    client.post("/vault/blocca/")
    assert client.get("/").url.startswith("/vault/sblocca/")
    new = "a brand new passphrase"
    client.post("/vault/passphrase-dimenticata/", {"code": code, "passphrase": new, "confirm": new})
    assert client.get("/").status_code == 200
    with pytest.raises(vault.VaultError):
        vault.unlock_private_key(user, PASSPHRASE)
    assert vault.unlock_private_key(user, new)


@pytest.mark.django_db
def test_cookie_is_bound_to_session(client, client_logged, user):
    stolen = client_logged.cookies[vault.COOKIE_NAME].value
    from django.test import Client

    attacker = Client()
    attacker.force_login(user)  # even with a valid login, another session can't reuse the keys
    attacker.cookies[vault.COOKIE_NAME] = stolen
    assert attacker.get("/").url.startswith("/vault/sblocca/")


@pytest.mark.django_db
def test_share_with_member(client, client_logged, keeper, user, hermanni):
    Specimen.objects.create(keeper=keeper, species=hermanni, name="Ercole")
    no_key = User.objects.create_user("nokey", "", "pw-test-123")
    terms.record(no_key)
    resp = client_logged.post("/account/detentore/membri/", {"username": "nokey", "role": "editor"}, follow=True)
    assert "non ha ancora configurato" in resp.content.decode()

    helper = make_vault_user("helper")
    client_logged.post("/account/detentore/membri/", {"username": "helper", "role": "editor"})
    from django.test import Client

    c2 = unlock_client(Client(), helper)
    assert "Ercole" in c2.get("/esemplari/").content.decode()

    # member without wrapped key (added before having a key pair) waits for re-sharing
    vault.create_user_key(no_key, PASSPHRASE)
    from apps.vault.models import UserKey

    UserKey.objects.filter(user=no_key).update(recovery_confirmed=True)
    no_key.private_key = vault.unlock_private_key(no_key, PASSPHRASE)
    c3 = unlock_client(Client(), no_key)
    assert c3.get("/esemplari/").url == "/vault/in-attesa/"


@pytest.mark.django_db
def test_existing_clear_profile_gets_encrypted(client, hermanni, office, django_capture_on_commit_callbacks):
    # data created before encryption existed: no key_id, clear rows and files
    with using(KeyRing()):
        legacy = Keeper.objects.create(first_name="Mario", last_name="Rossi", id_doc_number="AB1234567")
        legacy.id_doc_file.save("Rossi CI.pdf", ContentFile(b"%PDF-1.4 Mario Rossi"))
        sp = Specimen.objects.create(keeper=legacy, species=hermanni, name="Ercole", notes="via Roma")
        sp.notes = "Udine"
        sp.save()  # history rows in clear too
    assert "Rossi" in _dump_db() and "Ercole" in _dump_db()

    owner = make_vault_user("owner")
    Membership.objects.create(user=owner, keeper=legacy, role="owner")
    unlock_client(client, owner)
    assert client.get("/").url == "/vault/cifra-profilo/"
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post("/vault/cifra-profilo/").status_code == 302

    dump = _dump_db()
    for secret in ("Rossi", "Ercole", "AB1234567", "Udine", "via Roma"):
        assert secret not in dump, secret
    for p in Path(settings.MEDIA_ROOT).rglob("*"):
        if p.is_file():
            assert p.read_bytes().startswith(b"CITESENC1") and "Rossi" not in p.name
    # the owner's cookie now carries the new key: everything readable
    resp = client.get(f"/esemplari/{sp.pk}/")
    assert resp.status_code == 200 and "Ercole" in resp.content.decode()
    assert client.get(Keeper.objects.get(pk=legacy.pk).id_doc_file.url).status_code == 200


@pytest.mark.django_db
def test_recovery_page_does_not_replace_key_on_visit(client_logged, user):
    from apps.vault.models import UserKey

    before = bytes(UserKey.objects.get(user=user).private_by_recovery)
    assert client_logged.get("/vault/recupero/").status_code == 200
    assert bytes(UserKey.objects.get(user=user).private_by_recovery) == before
    resp = client_logged.post("/vault/recupero/", {"regenerate": "1"})
    code = re.search(r'id="code">([A-Z2-9-]+)<', resp.content.decode()).group(1)
    assert bytes(UserKey.objects.get(user=user).private_by_recovery) != before
    assert client_logged.get("/").url == "/vault/recupero/"  # new key must be confirmed
    client_logged.post("/vault/recupero/", {"code": code})
    assert client_logged.get("/").status_code == 200


@pytest.mark.django_db(transaction=True)
def test_failed_profile_encryption_keeps_original_data(hermanni, monkeypatch):
    with using(KeyRing()):
        legacy = Keeper.objects.create(first_name="Mario", last_name="Rossi")
        legacy.id_doc_file.save("Rossi CI.pdf", ContentFile(b"%PDF-1.4 Mario Rossi"))
        Specimen.objects.create(keeper=legacy, species=hermanni, name="Ercole")
    original = Keeper.objects.get(pk=legacy.pk).id_doc_file.name
    owner = make_vault_user("owner2")
    Membership.objects.create(user=owner, keeper=legacy, role="owner")

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    # fail after the keeper's file has been re-encrypted (specimens are processed later)
    monkeypatch.setattr(Specimen._meta.get_field("name"), "pre_save", boom)
    with using(vault.keyring_for(owner, owner.private_key)), pytest.raises(RuntimeError):
        vault.encrypt_keeper(Keeper.objects.get(pk=legacy.pk), owner)

    k = Keeper.objects.get(pk=legacy.pk)
    assert k.key_id is None and k.first_name == "Mario"  # rolled back, still clear
    assert k.id_doc_file.name == original
    assert (Path(settings.MEDIA_ROOT) / original).read_bytes() == b"%PDF-1.4 Mario Rossi"  # original file kept
