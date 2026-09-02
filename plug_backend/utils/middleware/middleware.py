import hmac
import ipaddress
import logging

from django.http import HttpResponseForbidden

logger = logging.getLogger(__name__)

# Cloudflare's published IP ranges.
# Kept as a defense-in-depth secondary check — not the primary gate anymore.
CLOUDFLARE_IP_RANGES = [
    # IPv4
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",

    # IPv6
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
]

CLOUDFLARE_NETWORKS = [
    ipaddress.ip_network(network)
    for network in CLOUDFLARE_IP_RANGES
]


def is_cloudflare_ip(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False

    return any(address in network for network in CLOUDFLARE_NETWORKS)


class CloudflareOnlyMiddleware:
    """
    Production:
        Only allow requests carrying the shared secret header that
        Cloudflare injects via a Transform Rule at the edge. This is
        the primary check because on platforms like Railway, the TCP
        connection to Django is made by Railway's own proxy layer, not
        directly by Cloudflare — so REMOTE_ADDR never reflects
        Cloudflare's edge IP, making IP-based verification unreliable
        here.

    Local development:
        Allow localhost/private development traffic when DEBUG=True.
    """

    HEADER_NAME = "HTTP_X_ORIGIN_AUTH"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings

        # Always allow local development.
        if settings.DEBUG:
            return self.get_response(request)

        provided_secret = request.META.get(self.HEADER_NAME, "")
        expected_secret = settings.CLOUDFLARE_ORIGIN_SECRET

        if not provided_secret or not hmac.compare_digest(
            provided_secret, expected_secret
        ):
            logger.warning(
                "CloudflareOnlyMiddleware: blocked request without valid "
                "origin secret. REMOTE_ADDR=%s CF-Ray=%s path=%s",
                request.META.get("REMOTE_ADDR", ""),
                request.META.get("HTTP_CF_RAY", ""),
                request.path,
            )
            return HttpResponseForbidden(
                "Direct access to this origin is not allowed."
            )

        return self.get_response(request)