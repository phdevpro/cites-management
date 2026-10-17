import pytest
from django.contrib.auth.models import User

from apps.accounts.models import Keeper, Membership
from apps.accounts.validators import codice_fiscale_is_valid
from apps.registry.models import Specimen


def test_codice_fiscale():
    assert codice_fiscale_is_valid("RSSMRA80A01H501U")
    assert not codice_fiscale_is_valid("RSSMRA80A01H501X")
    assert not codice_fiscale_is_valid("ABC")


@pytest.mark.django_db
def test_tenant_isolation(client, keeper, hermanni):
    sp = Specimen.objects.create(keeper=keeper, species=hermanni)
    other_keeper = Keeper.objects.create(first_name="Anna", last_name="Bianchi")
    other = User.objects.create_user("anna", "", "pw-test-123")
    Membership.objects.create(user=other, keeper=other_keeper)
    client.force_login(other)
    assert client.get(f"/esemplari/{sp.pk}/").status_code == 404
    assert "hermanni" not in client.get("/esemplari/?status=all").content.decode()


@pytest.mark.django_db
def test_viewer_cannot_edit(client, keeper, hermanni):
    viewer = User.objects.create_user("v", "", "pw-test-123")
    Membership.objects.create(user=viewer, keeper=keeper, role="viewer")
    client.force_login(viewer)
    assert client.get("/denunce/nascita/").status_code == 403


@pytest.mark.django_db
def test_signup_then_keeper_required(client):
    resp = client.post("/account/signup/", {"username": "new", "email": "n@example.com",
                                            "password1": "Very-Strong-pw-91", "password2": "Very-Strong-pw-91"})
    assert resp.status_code == 302
    assert client.get("/").url.endswith("/account/detentore/nuovo/")


@pytest.mark.django_db
def test_media_only_for_owner(client, keeper, user, tmp_path, settings):
    from django.core.files.base import ContentFile

    settings.MEDIA_ROOT = tmp_path
    keeper.id_doc_file.save("ci.pdf", ContentFile(b"%PDF secret"))
    url = keeper.id_doc_file.url
    assert client.get(url).status_code == 302  # login required
    other = User.objects.create_user("x", "", "pw-test-123")
    Membership.objects.create(user=other, keeper=Keeper.objects.create(first_name="O", last_name="T"))
    client.force_login(other)
    assert client.get(url).status_code == 404
    client.force_login(user)
    resp = client.get(url)
    assert resp.status_code == 200 and b"secret" in b"".join(resp.streaming_content)
    assert client.get("/media/../config/settings.py").status_code == 404
