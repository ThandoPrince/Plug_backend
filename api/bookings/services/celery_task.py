from celery import shared_task

from api.bookings.events.ws_events import notify_provider_booking_invite
from api.bookings.models import OrderService
from api.bookings.serializers import OrderServiceReadSerializer

from api.clientsDB.notifications.services.notification_builder import OrderNotificationBuilder
from api.clientsDB.notifications.services.notification_service import NotificationService

import logging

logger = logging.getLogger(__name__)

@shared_task
def process_order_created(order_id):
    order = (
        OrderService.objects
        .select_related("client", "service_required")
        .prefetch_related("invited_providers")
        .get(pk=order_id)
    )

    notification_payload = OrderNotificationBuilder.booking_invite(order)

    for provider in order.invited_providers.all():
        NotificationService.notify_provider(
            provider=provider,
            notification_type="booking_invite",
            title="New Booking Request 📩",
            body=f"{notification_payload['client_name']} created a booking.",
            payload=notification_payload,
            websocket_invite=True,
        )