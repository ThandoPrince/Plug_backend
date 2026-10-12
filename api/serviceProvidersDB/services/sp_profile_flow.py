from functools import wraps

from rest_framework import status
from rest_framework.response import Response

from api.serviceProvidersDB.models import SPProfile




class PS:
    EMAIL_VERIFICATION = "in-email-verification"
    DETAILS = "in-details"
    ADDRESS = "in-address"
    SERVICES = "in-services"
    COST = "in-cost"
    COMPLETED = "completed"


FLOW = [PS.EMAIL_VERIFICATION, PS.DETAILS, PS.ADDRESS,
        PS.SERVICES, PS.COST, PS.COMPLETED]

NEXT_STATUS = {FLOW[i]: FLOW[i + 1] for i in range(len(FLOW) - 1)}


def require_profile_status(*allowed):
    """
    Block the view unless the provider's status is one of `allowed`.
    Put it closest to the function, below @api_view / @permission_classes.
    """
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            current = getattr(request.user, "is_profile_completed", None)

            if current not in allowed:
                return Response(
                    {
                        "success": False,
                        "message": "This step is not available for your current profile status.",
                        "current_status": current,   # lets the app route to the right screen
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def advance_profile_status(sp, expected):
    """
    Atomically move `expected` -> next step. Returns False if the row is no
    longer in `expected` (double submit, race, another tab), so a step can
    never run twice or be skipped.
    """
    nxt = NEXT_STATUS.get(expected)
    if nxt is None:
        return False

    updated = (
        SPProfile.objects
        .filter(pk=sp.pk, is_profile_completed=expected)
        .update(is_profile_completed=nxt)
    )
    if updated:
        sp.is_profile_completed = nxt   # keep the in-memory object in sync
    return bool(updated)