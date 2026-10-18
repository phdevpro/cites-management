"""Security middleware: real client IP behind proxies, admin IP allowlist, Permissions-Policy."""

import ipaddress

from django.conf import settings
from django.http import Http404


def client_ip(request) -> str:
    """Client address as seen by the outermost trusted proxy.

    Each trusted proxy (Traefik, Cloudflare, ...) appends the address it received the request from
    to X-Forwarded-For, so the entry TRUSTED_PROXY_COUNT positions from the end is the real client;
    anything further left can be forged by the client itself."""
    hops = getattr(settings, "TRUSTED_PROXY_COUNT", 0)
    forwarded = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
    if hops and len(forwarded) >= hops:
        return forwarded[-hops][:45]
    return request.META.get("REMOTE_ADDR", "")[:45]


def ip_allowed(ip: str, networks) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in networks)


class AdminIPAllowlistMiddleware:
    """Hide the Django admin (404) from clients outside ADMIN_ALLOWED_IPS (when set)."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.prefix = "/" + settings.ADMIN_URL.lstrip("/")
        self.networks = [ipaddress.ip_network(n.strip(), strict=False)
                         for n in settings.ADMIN_ALLOWED_IPS if n.strip()]

    def __call__(self, request):
        if self.networks and request.path.startswith(self.prefix) and not ip_allowed(client_ip(request), self.networks):
            raise Http404
        return self.get_response(request)


class PermissionsPolicyMiddleware:
    """Deny powerful browser features the app never uses."""

    POLICY = ("accelerometer=(), autoplay=(), camera=(), display-capture=(), geolocation=(), gyroscope=(), "
              "magnetometer=(), microphone=(), midi=(), payment=(), publickey-credentials-get=(), usb=(), "
              "interest-cohort=()")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", self.POLICY)
        return response
