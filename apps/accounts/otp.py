"""Two-factor authentication (TOTP + one-time backup codes) for administrators.

Staff users (or everyone, with OTP_REQUIRED_FOR=all) must enroll an authenticator app and enter
a code after every login before reaching any page, the Django admin included.
"""

import base64
import io

import django_otp
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

EXEMPT_PREFIXES = ("/login/", "/logout/", "/account/2fa/", "/static/", "/favicon.ico", "/.well-known/",
                   "/termini/", "/privacy/")
BACKUP_CODES = 10


def otp_required(user) -> bool:
    mode = getattr(settings, "OTP_REQUIRED_FOR", "staff")
    if not user.is_authenticated or mode == "none":
        return False
    return mode == "all" or user.is_staff or user.is_superuser


def confirmed_totp(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).first()


class OTPGateMiddleware:
    """After django_otp's OTPMiddleware: send unverified administrators to enrolment / verification."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if otp_required(user) and not request.path.startswith(EXEMPT_PREFIXES) and not user.is_verified():
            target = "accounts:otp_verify" if confirmed_totp(user) else "accounts:otp_setup"
            url = reverse(target)
            if request.method == "GET":
                url += "?" + urlencode({"next": request.get_full_path()})
            return redirect(url)
        return self.get_response(request)


class TokenForm(forms.Form):
    token = forms.CharField(label="Codice", max_length=16,
                            widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "inputmode": "numeric",
                                                          "autofocus": True}))

    def clean_token(self):
        return self.cleaned_data["token"].replace(" ", "").replace("-", "").strip()


def _next(request):
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(nxt, {request.get_host()}, request.is_secure()):
        return nxt
    return reverse("dashboard:home")


def _qr_data_uri(text: str) -> str:
    import qrcode

    img = qrcode.make(text, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _new_backup_codes(user) -> list[str]:
    device, _ = StaticDevice.objects.get_or_create(user=user, name="backup", defaults={"confirmed": True})
    device.token_set.all().delete()
    codes = [StaticToken.random_token() for _ in range(BACKUP_CODES)]
    for code in codes:
        device.token_set.create(token=code)
    return codes


@login_required
def setup(request):
    """Enrol an authenticator app: QR code + secret, confirm with a first code, then show backup codes once."""
    if confirmed_totp(request.user) and not request.user.is_verified():
        return redirect("accounts:otp_verify")
    with transaction.atomic():
        device = TOTPDevice.objects.filter(user=request.user, confirmed=False).first() or TOTPDevice.objects.create(
            user=request.user, name="app", confirmed=False)
    form = TokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        allowed, _ = device.verify_is_allowed()
        if not allowed:
            form.add_error("token", "Troppi tentativi errati: attendi qualche secondo e riprova.")
        elif device.verify_token(form.cleaned_data["token"]):
            with transaction.atomic():
                TOTPDevice.objects.filter(user=request.user, confirmed=True).delete()  # replacing an old phone
                device.confirmed = True
                device.save()
                codes = _new_backup_codes(request.user)
            django_otp.login(request, device)
            messages.success(request, "Autenticazione a due fattori attivata.")
            return render(request, "accounts/otp_backup.html", {"codes": codes, "next": _next(request)})
        else:
            form.add_error("token", "Codice non valido: controlla l'ora del telefono e riprova.")
    secret = base64.b32encode(device.bin_key).decode().rstrip("=")
    return render(request, "accounts/otp_setup.html", {
        "form": form, "qr": _qr_data_uri(device.config_url), "secret": " ".join(secret[i:i + 4] for i in range(0, len(secret), 4)),
        "next": request.GET.get("next", ""),
    })


@login_required
def verify(request):
    """Second step after login: code from the app, or one of the backup codes."""
    totp = confirmed_totp(request.user)
    if totp is None:
        return redirect("accounts:otp_setup")
    if request.user.is_verified():
        return redirect(_next(request))
    form = TokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        token = form.cleaned_data["token"]
        # 6 digits = authenticator app; anything else = a one-time backup code (separate throttling)
        devices = [totp] if token.isdigit() and len(token) == totp.digits else \
            list(StaticDevice.objects.filter(user=request.user, confirmed=True))
        if any(not d.verify_is_allowed()[0] for d in devices):
            form.add_error("token", "Troppi tentativi errati: attendi qualche secondo e riprova.")
        else:
            for device in devices:
                if device.verify_token(token):
                    django_otp.login(request, device)
                    if isinstance(device, StaticDevice):
                        messages.warning(request, f"Hai usato un codice di backup: ne restano {device.token_set.count()}.")
                    return redirect(_next(request))
            form.add_error("token", "Codice non valido.")
    return render(request, "accounts/otp_verify.html", {"form": form, "next": request.GET.get("next", "")})


@login_required
def backup_codes(request):
    """Regenerate backup codes (only from a verified session)."""
    if not (confirmed_totp(request.user) and request.user.is_verified()):
        return redirect("accounts:otp_verify")
    if request.method == "POST":
        codes = _new_backup_codes(request.user)
        messages.success(request, "Nuovi codici di backup generati: quelli precedenti non valgono più.")
        return render(request, "accounts/otp_backup.html", {"codes": codes, "next": reverse("dashboard:home")})
    return render(request, "accounts/otp_backup.html", {"codes": None,
                                                        "left": StaticToken.objects.filter(device__user=request.user).count()})
