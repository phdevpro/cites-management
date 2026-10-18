import pytest
from django.contrib.auth.models import User

from apps.accounts import terms
from apps.accounts.models import TermsAcceptance
from conftest import unlock_client


@pytest.mark.django_db
def test_legal_pages_are_public(client, settings):
    settings.LEGAL = {**settings.LEGAL, "name": "Mario Bianchi", "forum": "Trento"}
    page = client.get("/termini/").content.decode()
    assert "Mario Bianchi" in page and "Trento" in page and "senza scopo di lucro" in page
    assert "perdita, corruzione, cancellazione" in page  # data-loss exclusion
    assert "1341" in page
    assert client.get("/privacy/").status_code == 200


@pytest.mark.django_db
def test_signup_requires_terms(client):
    data = {"username": "anna", "email": "a@example.com", "password1": "Very-Strong-pw-91",
            "password2": "Very-Strong-pw-91"}
    resp = client.post("/account/signup/", data)
    assert resp.status_code == 200 and not User.objects.filter(username="anna").exists()
    assert "Per continuare devi accettare" in resp.content.decode()
    client.post("/account/signup/", {**data, "accept_terms": "on", "accept_risk": "on"}, REMOTE_ADDR="10.1.2.3")
    row = TermsAcceptance.objects.get(user__username="anna")
    assert row.version == terms.current_version()
    assert row.clauses == "4, 5, 6, 9, 10, 11, 12, 15, 17"
    assert row.ip_address == "10.1.2.3"


@pytest.mark.django_db
def test_existing_users_must_accept_new_version(client, user, settings):
    unlock_client(client, user)
    assert client.get("/esemplari/").status_code == 200
    settings.LEGAL = {**settings.LEGAL, "version": "2099-01-01.1"}  # terms changed
    resp = client.get("/esemplari/")
    assert resp.url == "/account/termini/accetta/?next=%2Fesemplari%2F"
    assert client.get("/termini/").status_code == 200  # legal pages still reachable
    assert client.post("/account/termini/accetta/", {"next": "/esemplari/"}).status_code == 200  # unticked
    resp = client.post("/account/termini/accetta/", {"accept_terms": "on", "accept_risk": "on", "next": "/esemplari/"})
    assert resp.url == "/esemplari/"
    assert TermsAcceptance.objects.filter(user=user).count() == 2
    assert client.get("/esemplari/").status_code == 200


@pytest.mark.django_db
def test_accept_page_ignores_external_next(client, user):
    unlock_client(client, user)
    TermsAcceptance.objects.filter(user=user).delete()
    resp = client.post("/account/termini/accetta/", {"accept_terms": "on", "accept_risk": "on", "next": "https://evil.example"})
    assert resp.url == "/"


@pytest.mark.django_db
def test_terms_gate_comes_before_encryption_setup(client):
    u = User.objects.create_user("fresh", "", "pw-test-123")
    client.force_login(u)
    assert client.get("/").url.startswith("/account/termini/accetta/")
    client.post("/account/termini/accetta/", {"accept_terms": "on", "accept_risk": "on"})
    assert client.get("/").url == "/vault/configura/"



@pytest.mark.django_db
def test_risk_must_be_accepted_separately(client):
    data = {"username": "risky", "email": "r@example.com", "password1": "Very-Strong-pw-91",
            "password2": "Very-Strong-pw-91", "accept_terms": "on"}
    resp = client.post("/account/signup/", data)
    assert "esclusivo rischio" in resp.content.decode() and not User.objects.filter(username="risky").exists()
    page = client.get("/termini/").content.decode()
    assert "17. Assunzione del rischio" in page and "In breve: usi" in page
