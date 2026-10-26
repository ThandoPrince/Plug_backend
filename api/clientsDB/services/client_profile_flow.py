"""
Client onboarding flow: in-email-verification -> in-details -> in-address -> completed

Kept separate from the provider flow so each can change on its own.
Never log OTPs, tokens, emails or phone numbers here. IDs and IPs only.
"""
import logging
from functools import wraps

from rest_framework import status
from rest_framework.response import Response

from api.clientsDB.models.models import ClientAuth
from api.clientsDB.services.client_ip_address_helper import get_client_ip



logger = logging.getLogger("client.profile_flow")


class CS:
    EMAIL_VERIFICATION = "in-email-verification"
    DETAILS = "in-details"
    ADDRESS = "in-address"
    COMPLETED = "completed"


CLIENT_FLOW = [CS.EMAIL_VERIFICATION, CS.DETAILS, CS.ADDRESS, CS.COMPLETED]

CLIENT_NEXT = {
    CLIENT_FLOW[i]: CLIENT_FLOW[i + 1] for i in range(len(CLIENT_FLOW) - 1)
}


def require_client_status(*allowed, require_verified=True):
    """
    Block the view unless request.user is an active ClientAuth whose
    is_profile_completed is one of `allowed`.

    Place it closest to the function, below @api_view / @permission_classes.
    Statuses outside the flow (e.g. legacy "in-kyc" / "is_blocked") are
    rejected automatically because they are never in `allowed`.

    require_verified: also demand email_verified_at is set (defense in depth).
    Pass False only for views that run before verification completes.
    """
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            current = getattr(user, "is_profile_completed", None)
            client_id = getattr(user, "pk", None)
            ip = get_client_ip(request)

            if not isinstance(user, ClientAuth) or not user.is_active:
                logger.warning(
                    "client_flow event=status_rejected view=%s client=%s "
                    "reason=not_active_client ip=%s",
                    view.__name__, client_id, ip,
                )
                return Response(
                    {"success": False, "message": "Account not available."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if current not in allowed:
                logger.warning(
                    "client_flow event=status_rejected view=%s client=%s "
                    "status=%s allowed=%s ip=%s",
                    view.__name__, client_id, current, list(allowed), ip,
                )
                return Response(
                    {
                        "success": False,
                        "message": "This step is not available for your current profile status.",
                        "current_status": current,  # lets the app route to the right screen
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            if require_verified and user.email_verified_at is None:
                logger.warning(
                    "client_flow event=status_rejected view=%s client=%s "
                    "reason=email_not_verified ip=%s",
                    view.__name__, client_id, ip,
                )
                return Response(
                    {
                        "success": False,
                        "message": "Please verify your email first.",
                        "current_status": current,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def advance_client_status(client, expected):
    """
    Atomically move `expected` -> next step. Returns False if the row is no
    longer in `expected` (double submit, race, second device), so a step can
    never run twice or be skipped. Updates the in-memory object on success.
    """
    nxt = CLIENT_NEXT.get(expected)
    if nxt is None:
        return False

    updated = (
        ClientAuth.objects
        .filter(pk=client.pk, is_profile_completed=expected, is_active=True)
        .update(is_profile_completed=nxt)
    )

    if updated:
        client.is_profile_completed = nxt
        logger.info(
            "client_flow event=advanced client=%s from=%s to=%s",
            client.pk, expected, nxt,
        )
    else:
        logger.warning(
            "client_flow event=advance_conflict client=%s expected=%s",
            client.pk, expected,
        )
    return bool(updated)