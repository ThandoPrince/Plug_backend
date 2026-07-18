# api/bookings/events/handlers/order_created_handler.py

import logging

from api.bookings.events.ws_events import notify_provider_booking_invite
from api.bookings.serializers import OrderServiceReadSerializer


logger = logging.getLogger(__name__)


class OrderCreatedHandler:
    """
    Publishes newly created bookings to all invited providers.
    """

    @staticmethod
    def handle(event):
        try:
            order = event.payload

            serializer = OrderServiceReadSerializer(order)
            payload = serializer.data

            for provider in order.invited_providers.all():

                notify_provider_booking_invite(
                    provider_id=provider.id,
                    payload=payload,
                )

        except Exception:
            logger.exception(
                "Failed to publish booking invites for order %s.",
                getattr(event.payload, "order_id", "unknown"),
            )