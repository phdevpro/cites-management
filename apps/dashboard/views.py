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
