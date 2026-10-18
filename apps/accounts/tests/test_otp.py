import re

import pytest
from django.core.management import call_command
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from conftest import make_vault_user, unlock_client


def code_for(device):
    return f"{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits, drift=device.drift):06d}"


@pytest.fixture
def admin_user(db):
    u = make_vault_user("boss")
    u.is_staff = u.is_superuser = True
    u.save()
    return u


@pytest.mark.django_db
def test_admin_must_enrol_then_verify_every_login(client, admin_user, settings):
    unlock_client(client, admin_user)
    resp = client.get("/esemplari/")
    assert resp.url.startswith("/account/2fa/configura/")
    page = client.get(resp.url).content.decode()
    assert 'src="data:image/png;base64,' in page and "Codice segreto" in page
    device = TOTPDevice.objects.get(user=admin_user, confirmed=False)

    assert "Codice non valido" in client.post("/account/2fa/configura/", {"token": "000000"}).content.decode()
    assert "Troppi tentativi" in client.post("/account/2fa/configura/", {"token": code_for(device)}).content.decode()
    device.refresh_from_db()
    device.throttle_reset()  # (the throttling window would have passed)
    resp = client.post("/account/2fa/configura/", {"token": code_for(device), "next": "/esemplari/"})
    codes = re.findall(r'<div class="col">([a-z0-9]+)</div>', resp.content.decode())
    assert len(codes) == 10 and TOTPDevice.objects.get(user=admin_user).confirmed
    assert client.get(f"/{settings.ADMIN_URL}").status_code == 200  # verified session reaches the admin

    # new login: code required before any page, admin included
    client.logout()
    unlock_client(client, admin_user)
    assert client.get(f"/{settings.ADMIN_URL}").url.startswith("/account/2fa/verifica/")
    assert client.get("/account/2fa/configura/").url == "/account/2fa/verifica/"  # can't re-enrol to bypass
    assert "Codice non valido" in client.post("/account/2fa/verifica/", {"token": "123456"}).content.decode()
    TOTPDevice.objects.get(user=admin_user).throttle_reset()  # (the throttling window would have passed)

    # a backup code works exactly once
    resp = client.post("/account/2fa/verifica/", {"token": codes[0], "next": "/esemplari/"})
    assert resp.url == "/esemplari/"
    assert StaticToken.objects.filter(device__user=admin_user).count() == 9
    client.logout()
    unlock_client(client, admin_user)
    assert "Codice non valido" in client.post("/account/2fa/verifica/", {"token": codes[0]}).content.decode()


@pytest.mark.django_db
def test_regular_users_not_affected_unless_required_for_all(client_logged, user, settings):
    assert client_logged.get("/esemplari/").status_code == 200
    settings.OTP_REQUIRED_FOR = "all"
    assert client_logged.get("/esemplari/").url.startswith("/account/2fa/configura/")


@pytest.mark.django_db
def test_reset_2fa_command(client, admin_user):
    TOTPDevice.objects.create(user=admin_user, name="app", confirmed=True)
    call_command("reset_2fa", "boss")
    assert not TOTPDevice.objects.filter(user=admin_user).exists()
    unlock_client(client, admin_user)
    assert client.get("/").url.startswith("/account/2fa/configura/")


@pytest.mark.django_db
def test_totp_secrets_not_in_admin(client, admin_user, settings):
    from django.contrib import admin
    from django_otp.plugins.otp_totp.models import TOTPDevice as T

    assert not admin.site.is_registered(T)


@pytest.mark.django_db
def test_new_admin_goes_through_2fa_terms_and_encryption_without_loops(client, settings):
    """Regression: the 2FA and terms gates redirected to each other, nesting `next` until the URL was too long."""
    from django.contrib.auth.models import User

    admin = User.objects.create_user("fresh-admin", "f@example.com", "pw-test-123", is_staff=True, is_superuser=True)
    client.force_login(admin)

    def land(url):
        resp = client.get(url, follow=True)
        assert len(resp.redirect_chain) <= 2, resp.redirect_chain
        assert resp.status_code == 200
        assert all(len(u) < 300 for u, _ in resp.redirect_chain)
        return resp.request["PATH_INFO"]

    # 1. two-factor setup first, reachable from anywhere (terms and encryption must not bounce it)
    assert land("/esemplari/") == "/account/2fa/configura/"
    assert land(f"/{settings.ADMIN_URL}") == "/account/2fa/configura/"
    assert land("/account/termini/accetta/") == "/account/2fa/configura/"
    device = TOTPDevice.objects.get(user=admin)
    client.post("/account/2fa/configura/", {"token": code_for(device)})

    # 2. then the terms
    assert land("/esemplari/") == "/account/termini/accetta/"
    client.post("/account/termini/accetta/", {"accept_terms": "on", "accept_risk": "on"})

    # 3. then the encryption setup
    assert land("/esemplari/") == "/vault/configura/"
