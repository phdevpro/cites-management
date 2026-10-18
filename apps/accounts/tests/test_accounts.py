import pytest

from apps.accounts.models import Keeper, Membership
from apps.accounts.validators import codice_fiscale_is_valid
from apps.registry.models import Specimen
from apps.vault import services as vault
from conftest import make_vault_user, unlock_client


def test_codice_fiscale():
    assert codice_fiscale_is_valid("RSSMRA80A01H501U")
    assert not codice_fiscale_is_valid("RSSMRA80A01H501X")
    assert not codice_fiscale_is_valid("ABC")


def _other_keeper_user(username="anna"):
    other_keeper = Keeper(first_name="Anna", last_name="Bianchi")
    dek = vault.new_keeper_key(other_keeper)
    other_keeper.save()
    other = make_vault_user(username)
    vault.share_with(Membership.objects.create(user=other, keeper=other_keeper), dek)
    return other


@pytest.mark.django_db
def test_tenant_isolation(client, keeper, hermanni):
    sp = Specimen.objects.create(keeper=keeper, species=hermanni)
    unlock_client(client, _other_keeper_user())
    assert client.get(f"/esemplari/{sp.pk}/").status_code == 404
    assert "hermanni" not in client.get("/esemplari/?status=all").content.decode()


@pytest.mark.django_db
def test_viewer_cannot_edit(client, keeper, hermanni):
    viewer = make_vault_user("v")
    vault.share_with(Membership.objects.create(user=viewer, keeper=keeper, role="viewer"), keeper.dek)
    unlock_client(client, viewer)
    assert client.get("/denunce/nascita/").status_code == 403


@pytest.mark.django_db
def test_signup_then_keeper_required(client):
    resp = client.post("/account/signup/", {"username": "new", "email": "n@example.com",
                                            "password1": "Very-Strong-pw-91", "password2": "Very-Strong-pw-91"})
    assert resp.status_code == 302
    assert client.get("/").url == "/vault/configura/"  # encryption keys first


@pytest.mark.django_db
def test_media_only_for_owner(client, keeper, user, tmp_path, settings):
    from django.core.files.base import ContentFile

    keeper.id_doc_file.save("ci.pdf", ContentFile(b"%PDF secret"))
    url = keeper.id_doc_file.url
    assert client.get(url).status_code == 302  # login required
    unlock_client(client, _other_keeper_user("x"))
    assert client.get(url).status_code == 404
    unlock_client(client, user)
    resp = client.get(url)
    assert resp.status_code == 200 and b"secret" in b"".join(resp.streaming_content)
    assert client.get("/media/../config/settings.py").status_code == 404
