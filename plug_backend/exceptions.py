import logging
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)

def custom_exception_handler(exc, context):
    """
    Global DRF exception handler:
    - Prevents stack traces leaking to frontend
    - Keeps response format controlled
    - Logs full error internally
    """

    # Let DRF handle known exceptions first
    response = exception_handler(exc, context)

    # If DRF already handled it, just normalize format
    if response is not None:
        response.data = {
            "success": False,
            "message": _extract_message(response.data)
        }
        return response

    # 🚨 Unhandled exceptions (THIS is where stack traces leak)
    logger.exception("Unhandled server error", exc_info=exc)

    return Response(
        {
            "success": False,
            "message": "Unexpected server error"
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR
    )


def _extract_message(data):
    """
    Normalizes DRF validation errors into a single string
    without changing frontend structure.
    """
    if isinstance(data, dict):
        # DRF serializer errors
        messages = []
        for k, v in data.items():
            if isinstance(v, list):
                messages.append(f"{k}: {v[0]}")
            else:
                messages.append(f"{k}: {v}")
        return " | ".join(messages)

    return str(data)