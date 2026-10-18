"""Terms of service acceptance (proof kept per art. 1341-1342 c.c.). See TermsAcceptance."""

from django.conf import settings

from .models import TermsAcceptance


def current_version() -> str:
    return settings.LEGAL.get("version") or settings.LEGAL["updated"]


def needs_acceptance(user) -> bool:
    return not TermsAcceptance.objects.filter(user=user, version=current_version()).exists()


def client_ip(request) -> str:
    from config.security import client_ip as real_ip

    return real_ip(request)


def record(user, request=None) -> TermsAcceptance:
    row, _ = TermsAcceptance.objects.get_or_create(
        user=user, version=current_version(),
        defaults={"clauses": settings.LEGAL["clauses"], "ip_address": client_ip(request) if request else ""},
    )
    return row
