from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import services
from .models import UserKey


class PassphraseForm(forms.Form):
    passphrase = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                                 label="Passphrase di cifratura", min_length=services.MIN_PASSPHRASE,
                                 help_text=f"Almeno {services.MIN_PASSPHRASE} caratteri. Diversa dalla password di accesso.")
    confirm = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}), label="Ripeti passphrase")

    def clean(self):
        cd = super().clean()
        if cd.get("passphrase") and cd.get("passphrase") != cd.get("confirm"):
            raise forms.ValidationError("Le passphrase non coincidono.")
        return cd


class UnlockForm(forms.Form):
    passphrase = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "autofocus": True}),
                                 label="Passphrase di cifratura")


class RecoveryConfirmForm(forms.Form):
    code = forms.CharField(label="Chiave di recupero", widget=forms.TextInput(attrs={"autocomplete": "off"}),
                           help_text="Digitala o incollala dal file salvato per confermare di averla conservata.")


class RecoverForm(PassphraseForm):
    code = forms.CharField(label="Chiave di recupero", widget=forms.TextInput(attrs={"autocomplete": "off"}))
    field_order = ["code", "passphrase", "confirm"]


class ChangeForm(PassphraseForm):
    current = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
                              label="Passphrase attuale")
    field_order = ["current", "passphrase", "confirm"]


def _next(request, default="dashboard:home"):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}, request.is_secure()):
        return nxt
    return default


def _load(request, private: bytes):
    """Replace the request key ring in place (the context var points to the same object)."""
    fresh = services.keyring_for(request.user, private)
    request.vault.private_key = fresh.private_key
    request.vault.keys = fresh.keys
    request.vault.keeper_keys = fresh.keeper_keys
    request.vault.dirty = True


def _show_recovery(request, code, first_time):
    return render(request, "vault/recovery.html", {"code": code, "form": RecoveryConfirmForm(),
                                                   "first_time": first_time, "username": request.user.username})


@login_required
def setup(request):
    if UserKey.objects.filter(user=request.user).exists():
        return redirect("vault:unlock")
    form = PassphraseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            private, code = services.create_user_key(request.user, form.cleaned_data["passphrase"])
        except services.VaultError as exc:
            form.add_error("passphrase", str(exc))
        else:
            _load(request, private)
            return _show_recovery(request, code, first_time=True)
    return render(request, "vault/setup.html", {"form": form})


@login_required
def recovery(request):
    """Confirm the recovery key (mandatory after setup) or, on explicit request, replace it."""
    uk = UserKey.objects.filter(user=request.user).first()
    if uk is None:
        return redirect("vault:setup")
    regenerate = request.method == "POST" and "regenerate" in request.POST
    if request.method == "POST" and not regenerate:
        form = RecoveryConfirmForm(request.POST)
        if form.is_valid():
            try:
                services.confirm_recovery(request.user, form.cleaned_data["code"])
            except services.VaultError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, "Chiave di recupero confermata. I tuoi dati sono cifrati.")
                return redirect(_next(request))
        return render(request, "vault/recovery.html", {"form": form, "code": None, "confirmed": uk.recovery_confirmed})
    if uk.recovery_confirmed and not regenerate:
        # already confirmed: offer replacement only via an explicit POST
        return render(request, "vault/recovery.html", {"form": None, "code": None, "confirmed": True})
    if not request.vault.private_key:
        return redirect(f"{reverse('vault:unlock')}?next={reverse('vault:recovery')}")
    code = services.new_recovery_code(request.user, request.vault.private_key)
    return _show_recovery(request, code, first_time=False)


@login_required
def unlock(request):
    if not UserKey.objects.filter(user=request.user).exists():
        return redirect("vault:setup")
    form = UnlockForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            private = services.unlock_private_key(request.user, form.cleaned_data["passphrase"])
        except services.VaultError as exc:
            form.add_error("passphrase", str(exc))
        else:
            _load(request, private)
            return redirect(_next(request))
    return render(request, "vault/unlock.html", {"form": form, "next": _next(request, "")})


@login_required
def recover(request):
    """Forgotten passphrase: recovery key + new passphrase."""
    form = RecoverForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            private = services.private_key_from_recovery(request.user, form.cleaned_data["code"])
            services.set_passphrase(request.user, private, form.cleaned_data["passphrase"])
        except services.VaultError as exc:
            form.add_error(None, str(exc))
        else:
            _load(request, private)
            messages.success(request, "Nuova passphrase impostata.")
            return redirect("dashboard:home")
    return render(request, "vault/form.html", {"form": form, "title": "Passphrase dimenticata",
                                               "intro": "Inserisci la chiave di recupero e scegli una nuova passphrase."})


@login_required
def change(request):
    form = ChangeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            private = services.unlock_private_key(request.user, form.cleaned_data["current"])
            services.set_passphrase(request.user, private, form.cleaned_data["passphrase"])
        except services.VaultError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Passphrase aggiornata.")
            return redirect("dashboard:home")
    return render(request, "vault/form.html", {"form": form, "title": "Cambia passphrase di cifratura",
                                               "intro": "La chiave di recupero resta valida."})


@login_required
def encrypt_profile(request):
    keeper = getattr(request, "keeper", None)
    if keeper is None or keeper.key_id:
        return redirect("dashboard:home")
    is_owner = request.membership.role == "owner"
    if request.method == "POST" and is_owner:
        if not request.vault.private_key:
            return redirect("vault:unlock")
        services.encrypt_keeper(keeper, request.user)
        request.vault.dirty = True
        messages.success(request, "Profilo cifrato: dati e documenti esistenti sono ora protetti.")
        return redirect("dashboard:home")
    return render(request, "vault/encrypt_profile.html", {"keeper": keeper, "is_owner": is_owner})


@login_required
def pending(request):
    return render(request, "vault/pending.html", {"memberships": request.user.memberships.select_related("keeper")})


@login_required
@require_POST
def lock(request):
    request._vault_clear = True
    request.vault.private_key = None
    request.vault.keys.clear()
    messages.info(request, "Dati bloccati.")
    return redirect("vault:unlock")
