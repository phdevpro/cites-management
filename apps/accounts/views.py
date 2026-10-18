from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.vault import services as vault

from . import terms
from .forms import AIKeyForm, AcceptTermsForm, DetentionSiteForm, KeeperForm, MemberInviteForm, SignupForm
from .middleware import SESSION_KEY
from .models import DetentionSite, Membership


TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def turnstile_ok(request) -> bool:
    """Server-side check of the Cloudflare Turnstile token (skipped when Turnstile is not configured)."""
    if not settings.TURNSTILE_SECRET_KEY:
        return True
    token = request.POST.get("cf-turnstile-response", "")
    if not token:
        return False
    import json
    import urllib.parse
    import urllib.request

    body = urllib.parse.urlencode({"secret": settings.TURNSTILE_SECRET_KEY, "response": token,
                                   "remoteip": terms.client_ip(request)}).encode()
    try:
        with urllib.request.urlopen(TURNSTILE_VERIFY_URL, data=body, timeout=10) as resp:
            return bool(json.loads(resp.read()).get("success"))
    except (OSError, ValueError):
        return False


def signup(request):
    if not settings.ALLOW_SIGNUP:
        raise Http404("Registrazione disattivata")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not turnstile_ok(request):
            form.add_error(None, "Verifica anti-bot non superata: riprova.")
        else:
            user = form.save()
            terms.record(user, request)
            login(request, user)
            messages.success(request, "Account creato. Inserisci ora i dati del detentore.")
            return redirect("accounts:keeper_create")
    return render(request, "registration/signup.html", {"form": form,
                                                        "turnstile_site_key": settings.TURNSTILE_SITE_KEY})


@login_required
def accept_terms(request):
    form = AcceptTermsForm(request.POST or None)
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(nxt, {request.get_host()}, request.is_secure()):
        nxt = ""
    if request.method == "POST" and form.is_valid():
        terms.record(request.user, request)
        return redirect(nxt or "dashboard:home")
    return render(request, "accounts/accept_terms.html", {"form": form, "next": nxt,
                                                          "updated": terms.needs_acceptance(request.user)})


@login_required
def keeper_create(request):
    form = KeeperForm(request.POST or None, request.FILES or None)
    site_form = DetentionSiteForm(request.POST or None, prefix="site")
    if request.method == "POST" and form.is_valid() and site_form.is_valid():
        with transaction.atomic():
            keeper = form.save(commit=False)
            dek = vault.new_keeper_key(keeper)  # data key exists before anything is written
            keeper.save()
            request.vault.add(keeper.pk, keeper.key_id, dek)
            site = site_form.save(commit=False)
            site.keeper = keeper
            site.save()
            membership = Membership.objects.create(user=request.user, keeper=keeper, role=Membership.Role.OWNER)
            vault.share_with(membership, dek)
        request.session[SESSION_KEY] = keeper.pk
        messages.success(request, f"Detentore {keeper} creato.")
        return redirect("dashboard:home")
    return render(request, "accounts/keeper_form.html", {"form": form, "site_form": site_form, "creating": True})


@login_required
def keeper_edit(request):
    keeper = request.keeper
    if keeper is None:
        return redirect("accounts:keeper_create")
    if not request.membership.can_edit:
        raise PermissionDenied
    form = KeeperForm(request.POST or None, request.FILES or None, instance=keeper)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Dati detentore aggiornati.")
        return redirect("accounts:keeper_edit")
    return render(
        request,
        "accounts/keeper_form.html",
        {"form": form, "sites": keeper.sites.all(), "members": keeper.memberships.select_related("user"),
         "invite_form": MemberInviteForm(), "ai_form": AIKeyForm(), "ai_key_set": bool(keeper.ai_api_key),
         "ai_server_key": bool(getattr(settings, "REGOLO_API_KEY", "")),
         "ai_models": (settings.AI_OCR_MODEL, settings.AI_EXTRACT_MODEL)},
    )


@login_required
def site_edit(request, pk=None):
    if request.keeper is None or not request.membership.can_edit:
        raise PermissionDenied
    site = get_object_or_404(DetentionSite, pk=pk, keeper=request.keeper) if pk else None
    form = DetentionSiteForm(request.POST or None, instance=site)
    if request.method == "POST" and form.is_valid():
        site = form.save(commit=False)
        site.keeper = request.keeper
        site.save()
        if site.is_default:
            request.keeper.sites.exclude(pk=site.pk).update(is_default=False)
        messages.success(request, "Sito salvato.")
        return redirect("accounts:keeper_edit")
    return render(request, "accounts/site_form.html", {"form": form, "site": site})


@login_required
@require_POST
def member_invite(request):
    if request.keeper is None or request.membership.role != Membership.Role.OWNER:
        raise PermissionDenied
    form = MemberInviteForm(request.POST)
    if form.is_valid():
        user = User.objects.filter(username=form.cleaned_data["username"]).first()
        if not user:
            messages.error(request, "Utente non trovato.")
        else:
            membership, _ = Membership.objects.update_or_create(
                user=user, keeper=request.keeper, defaults={"role": form.cleaned_data["role"]}
            )
            if vault.share_with(membership, vault.keeper_dek(request.keeper)):
                messages.success(request, f"{user} aggiunto: può sbloccare i dati con la propria passphrase.")
            else:
                messages.warning(request, f"{user} aggiunto, ma non ha ancora configurato la cifratura: "
                                          "quando l'avrà fatto, aggiungilo di nuovo per condividere la chiave.")
    return redirect("accounts:keeper_edit")


@login_required
@require_POST
def ai_key(request):
    """Owner-only: set / remove / test the profile's Regolo.ai key (stored encrypted with the profile key)."""
    if request.keeper is None or request.membership.role != Membership.Role.OWNER:
        raise PermissionDenied
    from apps.importer import ai

    keeper = request.keeper
    form = AIKeyForm(request.POST)
    if not form.is_valid():
        return redirect("accounts:keeper_edit")
    if form.cleaned_data["remove"]:
        keeper.ai_api_key = ""
        keeper.save(update_fields=["ai_api_key"])
        messages.info(request, "Chiave Regolo rimossa: gli import useranno solo la lettura locale.")
        return redirect("accounts:keeper_edit")
    new_key = form.cleaned_data["api_key"]
    key = new_key or ai.key_for(keeper)
    problems = ai.check_key(key) if key else ["nessuna chiave impostata"]
    if new_key:
        keeper.ai_api_key = new_key
        keeper.save(update_fields=["ai_api_key"])
        messages.success(request, "Chiave Regolo salvata (cifrata).")
    if problems:
        for p in problems:
            messages.error(request, f"Verifica chiave: {p}")
    else:
        messages.success(request, "Verifica chiave riuscita: OCR ed estrazione disponibili.")
    return redirect("accounts:keeper_edit")


@login_required
@require_POST
def switch_keeper(request, pk):
    membership = get_object_or_404(Membership, user=request.user, keeper_id=pk)
    request.session[SESSION_KEY] = membership.keeper_id
    return redirect(request.POST.get("next") or "dashboard:home")
