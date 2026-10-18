from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode

from . import terms
from .models import Membership

SESSION_KEY = "current_keeper_id"


class CurrentKeeperMiddleware:
    """Attach request.keeper / request.membership for the active keeper (tenant)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.keeper = None
        request.membership = None
        if request.user.is_authenticated:
            memberships = Membership.objects.filter(user=request.user).select_related("keeper")
            wanted = request.session.get(SESSION_KEY)
            membership = None
            if wanted:
                membership = memberships.filter(keeper_id=wanted).first()
            if membership is None:
                membership = memberships.order_by("id").first()
            if membership:
                request.membership = membership
                request.keeper = membership.keeper
                request.session[SESSION_KEY] = membership.keeper_id
        return self.get_response(request)


TERMS_EXEMPT = ("/login/", "/logout/", "/termini/", "/privacy/", "/account/termini/", "/static/", "/favicon.ico")


class TermsAcceptanceMiddleware:
    """Users must accept the current Terms before anything else (also after the Terms change)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and not request.path.startswith(TERMS_EXEMPT) and terms.needs_acceptance(user):
            url = reverse("accounts:accept_terms")
            if request.method == "GET":
                url += "?" + urlencode({"next": request.get_full_path()})
            return redirect(url)
        return self.get_response(request)
