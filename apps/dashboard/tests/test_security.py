import re
from datetime import date

import pytest
from django.test import RequestFactory, override_settings

from apps.declarations import services
from config.security import client_ip

INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.I)
INLINE_HANDLER = re.compile(r"\son[a-z]+\s*=", re.I)


@pytest.mark.django_db
def test_csp_and_permissions_policy_headers(client):
    resp = client.get("/login/")
    csp = resp.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert "object-src 'none'" in csp and "frame-ancestors 'self'" in csp
    assert "camera=()" in resp.headers["Permissions-Policy"] and "geolocation=()" in resp.headers["Permissions-Policy"]


@pytest.mark.django_db
def test_no_inline_scripts_or_cdn_on_pages(client_logged, keeper, user, hermanni):
    res = services.register_birth(keeper=keeper, user=user, species=hermanni, birth_date=date(2024, 10, 18),
                                  rows=[services.NewbornSpec(quantity=9)])
    pages = ["/", "/esemplari/", f"/esemplari/{res.specimens[0].pk}/", "/denunce/", "/denunce/nascita/",
             f"/denunce/{res.declaration.pk}/", f"/denunce/{res.declaration.pk}/modulo/", "/importa/",
             "/account/detentore/", "/esemplari/registro/", "/termini/", "/vault/cambia-passphrase/"]
    for url in pages:
        html = client_logged.get(url).content.decode()
        assert not INLINE_SCRIPT.search(html), url
        assert not INLINE_HANDLER.search(html), (url, INLINE_HANDLER.search(html))
        assert "unpkg.com" not in html and "cdn.jsdelivr" not in html, url
        assert "/static/vendor/bootstrap/bootstrap.bundle.min.js" in html


def test_client_ip_ignores_forged_forwarded_for(settings):
    rf = RequestFactory()
    req = rf.get("/", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.9", REMOTE_ADDR="172.18.0.5")
    settings.TRUSTED_PROXY_COUNT = 1  # Traefik appended the real client last
    assert client_ip(req) == "203.0.113.9"
    settings.TRUSTED_PROXY_COUNT = 2  # Cloudflare + Traefik
    assert client_ip(req) == "6.6.6.6"
    settings.TRUSTED_PROXY_COUNT = 0
    assert client_ip(req) == "172.18.0.5"


@pytest.mark.django_db
def test_admin_ip_allowlist(client):
    from django.test import Client

    with override_settings(ADMIN_ALLOWED_IPS=["192.168.1.0/24"], TRUSTED_PROXY_COUNT=1):
        from config.security import AdminIPAllowlistMiddleware

        mw = AdminIPAllowlistMiddleware(lambda r: "ok")
        rf = RequestFactory()
        assert mw(rf.get("/admin/", HTTP_X_FORWARDED_FOR="192.168.1.50")) == "ok"
        with pytest.raises(Exception):
            mw(rf.get("/admin/", HTTP_X_FORWARDED_FOR="192.168.1.50, 8.8.8.8"))  # forged prefix, real IP outside
        assert mw(rf.get("/esemplari/", HTTP_X_FORWARDED_FOR="8.8.8.8")) == "ok"  # rest of the site unaffected


@pytest.mark.django_db
def test_security_txt(client, settings):
    settings.LEGAL = {**settings.LEGAL, "email": "sec@example.com"}
    body = client.get("/.well-known/security.txt").content.decode()
    assert "Contact: mailto:sec@example.com" in body and "Expires: " in body
    settings.LEGAL = {**settings.LEGAL, "email": ""}
    settings.SECURITY_CONTACT = ""
    assert client.get("/.well-known/security.txt").status_code == 404


@pytest.mark.django_db
def test_signup_can_be_disabled(client, settings):
    settings.ALLOW_SIGNUP = False
    assert client.get("/account/signup/").status_code == 404
    assert "Crea un account" not in client.get("/login/").content.decode()


@pytest.mark.django_db
def test_turnstile_required_when_configured(client, settings, monkeypatch):
    from django.contrib.auth.models import User

    settings.TURNSTILE_SITE_KEY, settings.TURNSTILE_SECRET_KEY = "site", "secret"
    page = client.get("/account/signup/").content.decode()
    assert 'data-sitekey="site"' in page and "challenges.cloudflare.com/turnstile" in page
    data = {"username": "bot", "email": "b@example.com", "password1": "Very-Strong-pw-91",
            "password2": "Very-Strong-pw-91", "accept_terms": "on"}
    assert "anti-bot" in client.post("/account/signup/", data).content.decode()
    assert not User.objects.filter(username="bot").exists()

    import io
    import urllib.parse
    import urllib.request

    sent = {}

    def fake_urlopen(url, data=None, timeout=None):
        sent.update(urllib.parse.parse_qs(data.decode()))
        return io.BytesIO(b'{"success": true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    resp = client.post("/account/signup/", {**data, "cf-turnstile-response": "tok"})
    assert resp.status_code == 302 and User.objects.filter(username="bot").exists()
    assert sent["secret"] == ["secret"] and sent["response"] == ["tok"]
