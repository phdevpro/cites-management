from django.conf import settings
from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode

from . import services
from .context import KeyRing, activate, deactivate
from .models import UserKey

EXEMPT_PREFIXES = ("/login/", "/logout/", "/account/signup/", "/vault/", "/static/", "/favicon.ico")


def _max_age():
    return getattr(settings, "VAULT_UNLOCK_MAX_AGE", 12 * 3600)


class VaultActivateMiddleware:
    """Load the unlocked key ring from the encrypted cookie into the request context.
    Must run before anything loads encrypted rows (e.g. the current keeper)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        r = None
        cookie = request.COOKIES.get(services.COOKIE_NAME)
        if cookie and request.user.is_authenticated and request.session.session_key:
            r = services.load_cookie(cookie, request.session.session_key, _max_age())
        request.vault = r or KeyRing()
        request.vault.dirty = False
        token = activate(request.vault)
        try:
            response = self.get_response(request)
        finally:
            deactivate(token)
        if getattr(request, "_vault_clear", False):
            response.delete_cookie(services.COOKIE_NAME)
        elif request.vault.dirty and request.vault.private_key and request.session.session_key:
            response.set_cookie(
                services.COOKIE_NAME, services.dump_cookie(request.vault, request.session.session_key),
                httponly=True, secure=not settings.DEBUG, samesite="Lax",
            )
        return response


class VaultGateMiddleware:
    """Force key setup / unlock before any page that may show personal data."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.path.startswith(EXEMPT_PREFIXES):
            target = self._gate(request)
            if target:
                return redirect(target)
        return self.get_response(request)

    def _gate(self, request):
        uk = UserKey.objects.filter(user=request.user).only("recovery_confirmed").first()
        if uk is None:
            return reverse("vault:setup")
        if not uk.recovery_confirmed:
            return reverse("vault:recovery")
        if not request.vault.private_key:
            return f"{reverse('vault:unlock')}?{urlencode({'next': request.get_full_path()})}"
        keeper = getattr(request, "keeper", None)
        if keeper is not None:
            if not keeper.key_id:
                return reverse("vault:encrypt_profile")
            if keeper.pk not in request.vault.keeper_keys:
                return reverse("vault:pending")
        return None


@receiver(user_logged_out)
def _forget_keys(sender, request, **kwargs):
    if request is not None:
        request._vault_clear = True
        if hasattr(request, "vault"):
            request.vault.private_key = None
            request.vault.keys.clear()
