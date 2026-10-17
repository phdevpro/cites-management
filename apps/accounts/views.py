from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import DetentionSiteForm, KeeperForm, MemberInviteForm, SignupForm
from .middleware import SESSION_KEY
from .models import DetentionSite, Membership


def signup(request):
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Account creato. Inserisci ora i dati del detentore.")
        return redirect("accounts:keeper_create")
    return render(request, "registration/signup.html", {"form": form})


@login_required
def keeper_create(request):
    form = KeeperForm(request.POST or None, request.FILES or None)
    site_form = DetentionSiteForm(request.POST or None, prefix="site")
    if request.method == "POST" and form.is_valid() and site_form.is_valid():
        with transaction.atomic():
            keeper = form.save()
            site = site_form.save(commit=False)
            site.keeper = keeper
            site.save()
            Membership.objects.create(user=request.user, keeper=keeper, role=Membership.Role.OWNER)
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
         "invite_form": MemberInviteForm()},
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
            Membership.objects.update_or_create(
                user=user, keeper=request.keeper, defaults={"role": form.cleaned_data["role"]}
            )
            messages.success(request, f"{user} aggiunto.")
    return redirect("accounts:keeper_edit")


@login_required
@require_POST
def switch_keeper(request, pk):
    membership = get_object_or_404(Membership, user=request.user, keeper_id=pk)
    request.session[SESSION_KEY] = membership.keeper_id
    return redirect(request.POST.get("next") or "dashboard:home")
