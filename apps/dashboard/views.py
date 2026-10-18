from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.declarations.models import Declaration

from .alerts import keeper_alerts, keeper_stats


@login_required
def home(request):
    if request.keeper is None:
        return redirect("accounts:keeper_create")
    keeper = request.keeper
    return render(request, "dashboard/home.html", {
        "alerts": keeper_alerts(keeper),
        "stats": keeper_stats(keeper),
        "recent": Declaration.objects.filter(keeper=keeper).prefetch_related("items__specimen__species")[:8],
    })


def guide(request):
    return render(request, "dashboard/guide.html")


def terms_page(request):
    return render(request, "legal/terms.html")


def privacy_page(request):
    return render(request, "legal/privacy.html")


def security_txt(request):
    """RFC 9116 security.txt; contact from SECURITY_CONTACT or LEGAL_EMAIL."""
    from datetime import timedelta

    from django.conf import settings
    from django.http import Http404, HttpResponse
    from django.utils import timezone

    contact = settings.SECURITY_CONTACT or settings.LEGAL.get("email", "")
    if not contact:
        raise Http404
    if "@" in contact and not contact.startswith("mailto:"):
        contact = f"mailto:{contact}"
    expires = (timezone.now() + timedelta(days=365)).replace(microsecond=0).isoformat()
    body = (f"Contact: {contact}\nExpires: {expires}\nPreferred-Languages: it, en\n"
            f"Canonical: {request.build_absolute_uri()}\n")
    return HttpResponse(body, content_type="text/plain; charset=utf-8")
